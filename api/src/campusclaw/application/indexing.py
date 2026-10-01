"""Durable material indexing and rebuild/reconciliation operations."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from campusclaw.application.extraction import (
    ExtractionError,
    UnsupportedFormatError,
    chunk_segments,
    extract_text,
    select_parser,
)
from campusclaw.application.providers import EmbeddingClient, ProviderFailure
from campusclaw.application.vector import QdrantVectorStore, VectorUnavailableError
from campusclaw.config import Settings
from campusclaw.domain.models import (
    IndexJobState,
    IndexVersionState,
    KnowledgeChunk,
    Material,
    MaterialIndexJob,
    MaterialIndexVersion,
    MaterialSearchState,
    MaterialState,
    RetrievalState,
)
from campusclaw.persistence.database import Database
from campusclaw.persistence.knowledge import KnowledgeRepository


@dataclass(frozen=True)
class IndexResult:
    material_id: uuid.UUID
    status: str
    chunks: int = 0
    semantic_ready: bool = False
    error_code: str | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_bounded(path: Path, maximum: int) -> bytes:
    if path.stat().st_size > maximum:
        raise ExtractionError("extraction_too_large")
    return path.read_bytes()


class IndexWorker:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        owner: str = "indexer",
        repository: KnowledgeRepository | None = None,
        embeddings: EmbeddingClient | None = None,
        vectors: QdrantVectorStore | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.owner = owner
        self.repository = repository or KnowledgeRepository()
        self.embeddings = embeddings or EmbeddingClient(settings)
        self.vectors = vectors or QdrantVectorStore(settings)

    def enqueue_ready_material(self, material_id: uuid.UUID) -> bool:
        with self.database.transaction() as session:
            material = session.get(Material, material_id)
            if material is None or material.state != MaterialState.READY.value:
                return False
            self.repository.enqueue_job(session, material)
        return True

    def claim(self) -> MaterialIndexJob | None:
        with self.database.transaction() as session:
            job = self.repository.claim_job(
                session,
                owner=self.owner,
                lease_seconds=self.settings.WORKER_LEASE_SECONDS,
            )
            if job is None:
                return None
            job_id = job.id
        # Return a detached identity-safe copy for a caller that only needs the ID.
        return MaterialIndexJob(id=job_id, material_id=job.material_id, class_id=job.class_id)

    def _publish_vectors(self, chunks: list[KnowledgeChunk]) -> None:
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), self.settings.EMBEDDING_BATCH_SIZE):
            batch = chunks[start : start + self.settings.EMBEDDING_BATCH_SIZE]
            vectors.extend(self.embeddings.embed([chunk.text for chunk in batch]))
        self.vectors.ensure_collection()
        self.vectors.upsert(chunks, vectors)
        expected_ids = {chunk.id for chunk in chunks}
        if self.vectors.existing_ids(expected_ids) != expected_ids:
            raise VectorUnavailableError("vector_verification_failed")

    def _retry_semantic_index(
        self,
        *,
        job_id: uuid.UUID,
        material_id: uuid.UUID,
        class_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> IndexResult | None:
        """Complete vectors for the already-active keyword version using the same chunk IDs."""
        with self.database.transaction() as session:
            version = session.get(MaterialIndexVersion, version_id)
            if (
                version is None
                or version.material_id != material_id
                or version.class_id != class_id
                or version.build_state != IndexVersionState.READY.value
            ):
                return None
            chunks = list(
                session.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.index_version_id == version_id)
                    .order_by(KnowledgeChunk.ordinal)
                )
            )
        if not chunks:
            return None
        semantic_ready = False
        try:
            self._publish_vectors(chunks)
            semantic_ready = True
        except (ProviderFailure, VectorUnavailableError):
            pass
        with self.database.transaction() as session:
            state = session.scalar(
                select(MaterialSearchState).where(
                    MaterialSearchState.material_id == material_id,
                    MaterialSearchState.class_id == class_id,
                    MaterialSearchState.active_version_id == version_id,
                )
            )
            job = session.get(MaterialIndexJob, job_id)
            if state is None or job is None:
                return IndexResult(
                    material_id,
                    RetrievalState.FAILED.value,
                    error_code="source_missing",
                )
            state.status = RetrievalState.SEARCHABLE.value
            if semantic_ready:
                state.error_code = None
                state.next_retry_at = None
                job.state = IndexJobState.COMPLETE.value
                job.last_error_code = None
                job.next_retry_at = None
                job.lease_owner = None
                job.lease_expires_at = None
            else:
                retried = self.repository.retry_job(
                    session,
                    job_id,
                    error_code="semantic_pending",
                    max_attempts=self.settings.WORKER_MAX_ATTEMPTS,
                )
                state.error_code = "semantic_pending"
                state.next_retry_at = retried.next_retry_at if retried is not None else None
        return IndexResult(
            material_id,
            RetrievalState.SEARCHABLE.value,
            chunks=len(chunks),
            semantic_ready=semantic_ready,
            error_code=None if semantic_ready else "semantic_pending",
        )

    def process_one(self) -> IndexResult | None:
        with self.database.transaction() as session:
            job = self.repository.claim_job(
                session,
                owner=self.owner,
                lease_seconds=self.settings.WORKER_LEASE_SECONDS,
            )
            if job is None:
                return None
            job_id = job.id
            material = session.get(Material, job.material_id)
            if material is None or material.class_id != job.class_id:
                self.repository.retry_job(
                    session,
                    job_id,
                    error_code="source_missing",
                    max_attempts=self.settings.WORKER_MAX_ATTEMPTS,
                )
                return IndexResult(
                    job.material_id,
                    RetrievalState.FAILED.value,
                    error_code="source_missing",
                )
            material_id = material.id
            class_id = material.class_id
            storage_key = material.storage_key
            expected_sha = material.sha256
            content_type = material.content_type
            filename = material.original_filename
            state = self.repository.ensure_search_state(session, material)
            retry_version_id = (
                state.active_version_id
                if job.last_error_code == "semantic_pending"
                and state.status == RetrievalState.SEARCHABLE.value
                and job.desired_sha256 == material.sha256
                else None
            )
            if retry_version_id is None:
                state.status = RetrievalState.PROCESSING.value
            state.attempt_count = job.attempts
        if retry_version_id is not None:
            retried = self._retry_semantic_index(
                job_id=job_id,
                material_id=material_id,
                class_id=class_id,
                version_id=retry_version_id,
            )
            if retried is not None:
                return retried
        root = self.settings.UPLOAD_ROOT.resolve()
        try:
            path = (root / storage_key).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ExtractionError("source_missing")
            if _sha256_file(path) != expected_sha:
                raise ExtractionError("source_changed")
            data = _read_bounded(path, self.settings.EXTRACTION_MAX_BYTES)
            select_parser(content_type, filename, data[:8])
            segments = extract_text(
                data, content_type=content_type, filename=filename, settings=self.settings
            )
            chunks = chunk_segments(
                segments,
                chunk_chars=self.settings.EXTRACTION_CHUNK_CHARS,
                overlap_chars=self.settings.EXTRACTION_CHUNK_OVERLAP,
                max_chunks=self.settings.EXTRACTION_MAX_CHUNKS,
            )
        except UnsupportedFormatError:
            with self.database.transaction() as session:
                material = session.get(Material, material_id)
                if material is not None:
                    search_state = self.repository.ensure_search_state(session, material)
                    search_state.status = RetrievalState.UNSUPPORTED.value
                    search_state.error_code = "unsupported_format"
                job = session.get(MaterialIndexJob, job_id)
                if job is not None:
                    job.state = IndexJobState.COMPLETE.value
                    job.lease_owner = None
                    job.lease_expires_at = None
            return IndexResult(
                material_id,
                RetrievalState.UNSUPPORTED.value,
                error_code="unsupported_format",
            )
        except ExtractionError as exc:
            with self.database.transaction() as session:
                self.repository.mark_failed(session, material_id, error_code=exc.code)
                job = session.get(MaterialIndexJob, job_id)
                if job is not None:
                    self.repository.retry_job(
                        session,
                        job_id,
                        error_code=exc.code,
                        max_attempts=self.settings.WORKER_MAX_ATTEMPTS,
                    )
            return IndexResult(material_id, RetrievalState.FAILED.value, error_code=exc.code)
        except (OSError, ValueError):
            with self.database.transaction() as session:
                self.repository.mark_failed(session, material_id, error_code="source_unavailable")
                self.repository.retry_job(
                    session,
                    job_id,
                    error_code="source_unavailable",
                    max_attempts=self.settings.WORKER_MAX_ATTEMPTS,
                )
            return IndexResult(
                material_id,
                RetrievalState.FAILED.value,
                error_code="source_unavailable",
            )

        with self.database.transaction() as session:
            material = session.get(Material, material_id)
            if material is None or material.class_id != class_id:
                return IndexResult(
                    material_id,
                    RetrievalState.FAILED.value,
                    error_code="source_missing",
                )
            version = self.repository.create_version(
                session,
                material,
                embedding_model=self.settings.EMBEDDING_MODEL,
                vector_dimension=self.settings.EMBEDDING_DIMENSION,
            )
            for ordinal, chunk in enumerate(chunks):
                self.repository.add_chunk(
                    session,
                    version,
                    ordinal=ordinal,
                    text=chunk.text,
                    page=chunk.page,
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                    section_label=chunk.section_label,
                )
            version_id = version.id

        with self.database.transaction() as session:
            index_version = session.get(MaterialIndexVersion, version_id)
            if index_version is None:
                raise RuntimeError("index version disappeared")
            chunk_rows = list(
                session.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.index_version_id == version_id)
                    .order_by(KnowledgeChunk.ordinal)
                )
            )
        semantic_ready = False
        try:
            self._publish_vectors(chunk_rows)
            semantic_ready = True
        except (ProviderFailure, VectorUnavailableError):
            pass

        with self.database.transaction() as session:
            self.repository.activate_version(session, version_id, vector_ready=semantic_ready)
            job = session.get(MaterialIndexJob, job_id)
            if job is not None:
                job.lease_owner = None
                job.lease_expires_at = None
                if semantic_ready:
                    job.state = IndexJobState.COMPLETE.value
                    job.next_retry_at = None
                else:
                    retry_job_result = self.repository.retry_job(
                        session,
                        job_id,
                        error_code="semantic_pending",
                        max_attempts=self.settings.WORKER_MAX_ATTEMPTS,
                    )
                    pending_search_state = session.scalar(
                        select(MaterialSearchState).where(
                            MaterialSearchState.material_id == material_id
                        )
                    )
                    if pending_search_state is not None:
                        pending_search_state.next_retry_at = (
                            retry_job_result.next_retry_at if retry_job_result is not None else None
                        )
        return IndexResult(
            material_id,
            RetrievalState.SEARCHABLE.value,
            chunks=len(chunks),
            semantic_ready=semantic_ready,
            error_code=None if semantic_ready else "semantic_pending",
        )

    def reconcile_class(self, class_id: uuid.UUID) -> dict[str, int]:
        with self.database.transaction() as session:
            chunks = self.repository.active_chunks(session, class_id=class_id)
        report = self.vectors.reconcile(chunks, class_id=class_id)
        existing = self.vectors.existing_ids([chunk.id for chunk in chunks])
        missing = [chunk for chunk in chunks if chunk.id not in existing]
        repaired = 0
        if missing:
            try:
                for start in range(0, len(missing), self.settings.EMBEDDING_BATCH_SIZE):
                    batch = missing[start : start + self.settings.EMBEDDING_BATCH_SIZE]
                    vectors = self.embeddings.embed([chunk.text for chunk in batch])
                    self.vectors.upsert(batch, vectors)
                    repaired += len(batch)
            except (ProviderFailure, VectorUnavailableError):
                pass
        report["repaired"] = repaired
        return report

    def rebuild_vectors(self) -> int:
        self.vectors.ensure_collection()
        rebuilt = 0
        with self.database.transaction() as session:
            class_ids = list(
                session.scalars(
                    select(Material.class_id)
                    .where(Material.state == MaterialState.READY.value)
                    .distinct()
                )
            )
        for class_id in class_ids:
            with self.database.transaction() as session:
                chunks = self.repository.active_chunks(session, class_id=class_id)
            for start in range(0, len(chunks), self.settings.EMBEDDING_BATCH_SIZE):
                batch = chunks[start : start + self.settings.EMBEDDING_BATCH_SIZE]
                try:
                    vectors = self.embeddings.embed([chunk.text for chunk in batch])
                    self.vectors.upsert(batch, vectors)
                    rebuilt += len(batch)
                except (ProviderFailure, VectorUnavailableError):
                    return rebuilt
        return rebuilt

    def backfill(self) -> int:
        with self.database.transaction() as session:
            materials = list(
                session.scalars(select(Material).where(Material.state == MaterialState.READY.value))
            )
            for material in materials:
                self.repository.enqueue_job(session, material)
            return len(materials)

    def run_until_empty(self, *, max_jobs: int = 100) -> list[IndexResult]:
        results: list[IndexResult] = []
        for _ in range(max_jobs):
            result = self.process_one()
            if result is None:
                break
            results.append(result)
        return results


def aggregate_index_status(database: Database, class_id: uuid.UUID) -> dict[str, int]:
    with database.transaction() as session:
        return KnowledgeRepository().aggregate_status(session, class_id=class_id)
