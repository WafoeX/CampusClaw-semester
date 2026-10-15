"""Deterministic, session-class-scoped keyword/vector/hybrid retrieval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from campusclaw.application.providers import EmbeddingClient, ProviderFailure
from campusclaw.application.vector import QdrantVectorStore, VectorUnavailableError
from campusclaw.config import Settings
from campusclaw.domain.models import KnowledgeChunk
from campusclaw.persistence.knowledge import KnowledgeRepository

RequestedMode = Literal["keyword", "vector", "hybrid"]
EffectiveMode = Literal["keyword", "vector", "hybrid", "keyword_only"]


@dataclass(frozen=True)
class RetrievalResult:
    requested_mode: RequestedMode
    effective_mode: EffectiveMode
    chunks: list[KnowledgeChunk]
    degraded: bool = False


class VectorModeUnavailable(RuntimeError):
    pass


def reciprocal_rank_fusion(
    keyword: list[KnowledgeChunk],
    vector: list[KnowledgeChunk],
    *,
    constant: int,
    limit: int,
) -> list[KnowledgeChunk]:
    by_id: dict[uuid.UUID, KnowledgeChunk] = {}
    scores: dict[uuid.UUID, float] = {}
    for rank, chunk in enumerate(keyword, start=1):
        by_id[chunk.id] = chunk
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1 / (constant + rank)
    for rank, chunk in enumerate(vector, start=1):
        by_id[chunk.id] = chunk
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1 / (constant + rank)
    ordered = sorted(
        by_id.values(),
        key=lambda chunk: (-scores[chunk.id], chunk.material_id.hex, chunk.ordinal, chunk.id.hex),
    )
    return ordered[:limit]


class RetrievalService:
    def __init__(
        self,
        settings: Settings,
        repository: KnowledgeRepository | None = None,
        embeddings: EmbeddingClient | None = None,
        vectors: QdrantVectorStore | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository or KnowledgeRepository()
        self.embeddings = embeddings or EmbeddingClient(settings)
        self._owns_embeddings = embeddings is None
        self._owns_vectors = vectors is None
        self._vectors = vectors

    @property
    def vectors(self) -> QdrantVectorStore:
        # Do not contact a vector service when embeddings are unavailable and a
        # hybrid request can immediately degrade to authorized keyword retrieval.
        if self._vectors is None:
            self._vectors = QdrantVectorStore(self.settings)
        return self._vectors

    def close(self) -> None:
        if self._owns_embeddings:
            self.embeddings.http.close()
        if self._owns_vectors and self._vectors is not None:
            self._vectors.client.close()

    def retrieve(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        question: str,
        mode: RequestedMode,
        result_limit: int | None = None,
    ) -> RetrievalResult:
        normalized_question = question.strip()
        if not normalized_question or len(normalized_question) > self.settings.QUERY_MAX_LENGTH:
            raise ValueError("invalid_question")
        if mode not in {"keyword", "vector", "hybrid"}:
            raise ValueError("invalid_retrieval_mode")
        limit = min(
            result_limit or self.settings.QUERY_DEFAULT_RESULT_LIMIT,
            self.settings.QUERY_MAX_RESULT_LIMIT,
        )
        candidate_limit = min(self.settings.QUERY_MAX_CANDIDATES, max(limit, limit * 3))
        keyword = self.repository.keyword_search(
            session, class_id=class_id, question=normalized_question, limit=candidate_limit
        )
        if mode == "keyword":
            return RetrievalResult(mode, "keyword", keyword[:limit])
        try:
            query_vector = self.embeddings.embed_one(normalized_question)
            hits = self.vectors.search(
                class_id=class_id, vector=query_vector, limit=candidate_limit
            )
            ids = [hit.chunk_id for hit in hits]
            hydrated = self.repository.active_chunks(session, class_id=class_id, chunk_ids=ids)
            by_id = {chunk.id: chunk for chunk in hydrated}
            vector = [by_id[hit.chunk_id] for hit in hits if hit.chunk_id in by_id]
        except (VectorUnavailableError, ProviderFailure) as exc:
            if mode == "vector":
                raise VectorModeUnavailable("vector_unavailable") from exc
            return RetrievalResult(mode, "keyword_only", keyword[:limit], degraded=True)
        if mode == "vector":
            return RetrievalResult(mode, "vector", vector[:limit])
        return RetrievalResult(
            mode,
            "hybrid",
            reciprocal_rank_fusion(
                keyword,
                vector,
                constant=self.settings.QUERY_RRF_K,
                limit=limit,
            ),
        )
