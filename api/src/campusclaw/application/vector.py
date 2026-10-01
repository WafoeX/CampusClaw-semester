"""Qdrant adapter for derived, identifier-only semantic retrieval."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, cast

from qdrant_client import QdrantClient, models

from campusclaw.config import Settings
from campusclaw.domain.models import KnowledgeChunk


class VectorUnavailableError(RuntimeError):
    """The semantic dependency is unavailable; callers choose safe degradation."""


class VectorConfigurationError(RuntimeError):
    """The configured collection is incompatible with the embedding contract."""


@dataclass(frozen=True)
class VectorHit:
    chunk_id: uuid.UUID
    score: float


def point_id(chunk_id: uuid.UUID) -> str:
    """Qdrant's stable UUID representation; no translation table is required."""
    return str(chunk_id)


class QdrantVectorStore:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client or QdrantClient(
            url=settings.QDRANT_URL,
            api_key=(
                settings.QDRANT_API_KEY.get_secret_value() if settings.QDRANT_API_KEY else None
            ),
            timeout=max(1, int(settings.QDRANT_TIMEOUT_SECONDS)),
        )

    def ensure_collection(self) -> None:
        try:
            info = self.client.get_collection(self.settings.QDRANT_COLLECTION)
        except Exception:
            try:
                self.client.create_collection(
                    collection_name=self.settings.QDRANT_COLLECTION,
                    vectors_config=models.VectorParams(
                        size=self.settings.EMBEDDING_DIMENSION,
                        distance=getattr(models.Distance, self.settings.QDRANT_DISTANCE.upper()),
                    ),
                )
                return
            except Exception as create_exc:
                raise VectorUnavailableError("vector_store_unavailable") from create_exc
        config = getattr(info, "config", None)
        params = getattr(config, "params", None)
        vectors = getattr(params, "vectors", params)
        size = getattr(vectors, "size", None)
        distance = getattr(vectors, "distance", None)
        expected_distance = getattr(models.Distance, self.settings.QDRANT_DISTANCE.upper())
        if size != self.settings.EMBEDDING_DIMENSION or str(distance) != str(expected_distance):
            raise VectorConfigurationError("vector_collection_incompatible")

    def upsert(self, chunks: Iterable[KnowledgeChunk], vectors: Iterable[list[float]]) -> None:
        points: list[Any] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            if len(vector) != self.settings.EMBEDDING_DIMENSION:
                raise VectorConfigurationError("embedding_dimension_mismatch")
            points.append(
                models.PointStruct(
                    id=point_id(chunk.id),
                    vector=vector,
                    payload={
                        "class_id": str(chunk.class_id),
                        "material_id": str(chunk.material_id),
                        "index_version_id": str(chunk.index_version_id),
                    },
                )
            )
        if not points:
            return
        try:
            self.client.upsert(
                collection_name=self.settings.QDRANT_COLLECTION,
                points=points,
                wait=True,
            )
        except Exception as exc:
            raise VectorUnavailableError("vector_store_unavailable") from exc

    def search(self, *, class_id: uuid.UUID, vector: list[float], limit: int) -> list[VectorHit]:
        if len(vector) != self.settings.EMBEDDING_DIMENSION:
            raise VectorConfigurationError("embedding_dimension_mismatch")
        query_filter = models.Filter(
            must=[
                models.FieldCondition(key="class_id", match=models.MatchValue(value=str(class_id)))
            ]
        )
        try:
            if hasattr(self.client, "query_points"):
                result = self.client.query_points(
                    collection_name=self.settings.QDRANT_COLLECTION,
                    query=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=False,
                )
                points = getattr(result, "points", result)
            else:
                points = self.client.search(
                    collection_name=self.settings.QDRANT_COLLECTION,
                    query_vector=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=False,
                )
        except Exception as exc:
            raise VectorUnavailableError("vector_store_unavailable") from exc
        hits: list[VectorHit] = []
        for item in points:
            raw_id = getattr(item, "id", None)
            try:
                chunk_uuid = uuid.UUID(str(raw_id))
                score = float(getattr(item, "score", 0.0))
            except (TypeError, ValueError):
                continue
            hits.append(VectorHit(chunk_id=chunk_uuid, score=score))
        return hits[:limit]

    def existing_ids(self, ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
        requested = list(ids)
        if not requested:
            return set()
        try:
            records = self.client.retrieve(
                collection_name=self.settings.QDRANT_COLLECTION,
                ids=[point_id(item) for item in requested],
                with_payload=False,
                with_vectors=False,
            )
        except Exception as exc:
            raise VectorUnavailableError("vector_store_unavailable") from exc
        found: set[uuid.UUID] = set()
        for record in records:
            try:
                found.add(uuid.UUID(str(record.id)))
            except (TypeError, ValueError):
                continue
        return found

    def create_snapshot(self) -> str:
        try:
            snapshot = self.client.create_snapshot(collection_name=self.settings.QDRANT_COLLECTION)
            name = getattr(snapshot, "name", None)
            if not isinstance(name, str) or not name:
                raise ValueError
            return name
        except Exception as exc:
            raise VectorUnavailableError("vector_snapshot_unavailable") from exc

    def reconcile(
        self, expected: Iterable[KnowledgeChunk], *, class_id: uuid.UUID
    ) -> dict[str, int]:
        """Delete one class's orphan/incompatible points and report missing IDs."""
        expected_rows = list(expected)
        expected_ids = {chunk.id for chunk in expected_rows}
        class_filter = models.Filter(
            must=[
                models.FieldCondition(key="class_id", match=models.MatchValue(value=str(class_id)))
            ]
        )
        records: list[Any] = []
        offset: Any | None = None
        try:
            while True:
                page, next_offset = self.client.scroll(
                    collection_name=self.settings.QDRANT_COLLECTION,
                    scroll_filter=class_filter,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                records.extend(page)
                if next_offset is None:
                    break
                if next_offset == offset:
                    raise RuntimeError("qdrant scroll offset did not advance")
                offset = next_offset
        except Exception as exc:
            raise VectorUnavailableError("vector_store_unavailable") from exc
        expected_by_id = {chunk.id: chunk for chunk in expected_rows}
        stale: list[uuid.UUID | str | int] = []
        actual: set[uuid.UUID] = set()
        for record in records:
            raw_id = getattr(record, "id", None)
            try:
                record_id = uuid.UUID(str(raw_id))
            except (TypeError, ValueError):
                if isinstance(raw_id, str | int):
                    stale.append(raw_id)
                continue
            expected_row = expected_by_id.get(record_id)
            if expected_row is None:
                stale.append(record_id)
                continue
            payload = getattr(record, "payload", {}) or {}
            if payload != {
                "class_id": str(expected_row.class_id),
                "material_id": str(expected_row.material_id),
                "index_version_id": str(expected_row.index_version_id),
            }:
                stale.append(record_id)
                continue
            actual.add(record_id)
        self.delete_ids(stale)
        return {
            "expected": len(expected_ids),
            "missing": len(expected_ids - actual),
            "orphaned": len(stale),
            "deleted": len(stale),
        }

    def delete_ids(self, ids: Iterable[uuid.UUID | str | int]) -> None:
        requested = [point_id(item) if isinstance(item, uuid.UUID) else item for item in ids]
        if not requested:
            return
        try:
            self.client.delete(
                collection_name=self.settings.QDRANT_COLLECTION,
                points_selector=models.PointIdsList(points=cast(Any, requested)),
                wait=True,
            )
        except Exception as exc:
            raise VectorUnavailableError("vector_store_unavailable") from exc
