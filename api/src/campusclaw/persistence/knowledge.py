"""Authoritative PostgreSQL persistence for class-scoped knowledge retrieval."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

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

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")
CJK_RE = re.compile(r"^[\u3400-\u9fff]+$")


def normalize_search_text(value: str) -> str:
    """Normalize only for matching; ``KnowledgeChunk.text`` stays byte-faithful."""
    return " ".join(value.casefold().split())


def query_terms(question: str) -> list[str]:
    """Extract selective terms without turning every Chinese character into a hit."""
    normalized = normalize_search_text(question)
    terms: list[str] = []
    for token in TOKEN_RE.findall(normalized):
        if not CJK_RE.fullmatch(token) or len(token) <= 4:
            terms.append(token)
        else:
            # Four-character windows preserve useful phrases while avoiding the
            # broad one-character OR query that matches almost every document.
            terms.extend(token[index : index + 4] for index in range(len(token) - 3))
    if not terms and normalized:
        terms = [normalized]
    return list(dict.fromkeys(terms))


class KnowledgeRepository:
    """Small transaction-friendly primitives; callers provide class scope explicitly."""

    def ensure_search_state(self, session: Session, material: Material) -> MaterialSearchState:
        state = session.scalar(
            select(MaterialSearchState).where(MaterialSearchState.material_id == material.id)
        )
        if state is None:
            state = MaterialSearchState(material_id=material.id, class_id=material.class_id)
            session.add(state)
            session.flush()
        elif state.class_id != material.class_id:
            raise ValueError("material search state has mismatched class")
        return state

    def enqueue_job(
        self,
        session: Session,
        material: Material,
        *,
        now: datetime | None = None,
    ) -> MaterialIndexJob:
        if material.state != MaterialState.READY.value:
            raise ValueError("only ready materials can be indexed")
        self.ensure_search_state(session, material)
        job = session.scalar(
            select(MaterialIndexJob).where(
                MaterialIndexJob.material_id == material.id,
                MaterialIndexJob.desired_sha256 == material.sha256,
            )
        )
        if job is None:
            job = MaterialIndexJob(
                material_id=material.id,
                class_id=material.class_id,
                desired_sha256=material.sha256,
                state=IndexJobState.PENDING.value,
            )
            session.add(job)
        else:
            if job.class_id != material.class_id:
                raise ValueError("index job has mismatched class")
            if job.state == IndexJobState.FAILED.value:
                job.state = IndexJobState.PENDING.value
                job.next_retry_at = now
                job.last_error_code = None
        session.flush()
        return job

    def claim_job(
        self,
        session: Session,
        *,
        owner: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> MaterialIndexJob | None:
        current = now or datetime.now(UTC)
        eligible = or_(
            MaterialIndexJob.state == IndexJobState.PENDING.value,
            and_(
                MaterialIndexJob.state == IndexJobState.PROCESSING.value,
                MaterialIndexJob.lease_expires_at < current,
            ),
        )
        job = session.scalar(
            select(MaterialIndexJob)
            .where(
                eligible,
                or_(
                    MaterialIndexJob.next_retry_at.is_(None),
                    MaterialIndexJob.next_retry_at <= current,
                ),
            )
            .order_by(MaterialIndexJob.created_at, MaterialIndexJob.id)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.state = IndexJobState.PROCESSING.value
        job.lease_owner = owner
        job.lease_expires_at = current + timedelta(seconds=lease_seconds)
        job.attempts += 1
        session.flush()
        return job

    def retry_job(
        self,
        session: Session,
        job_id: uuid.UUID,
        *,
        error_code: str,
        max_attempts: int,
        delay_seconds: int = 30,
        now: datetime | None = None,
    ) -> MaterialIndexJob | None:
        job = session.get(MaterialIndexJob, job_id)
        if job is None:
            return None
        current = now or datetime.now(UTC)
        job.last_error_code = error_code[:80]
        job.lease_owner = None
        job.lease_expires_at = None
        if job.attempts >= max_attempts:
            job.state = IndexJobState.FAILED.value
            job.next_retry_at = None
        else:
            job.state = IndexJobState.PENDING.value
            job.next_retry_at = current + timedelta(seconds=max(1, delay_seconds))
        session.flush()
        return job

    def create_version(
        self,
        session: Session,
        material: Material,
        *,
        embedding_model: str,
        vector_dimension: int,
        extraction_version: str = "extract-v1",
        chunking_version: str = "chunk-v1",
    ) -> MaterialIndexVersion:
        if material.state != MaterialState.READY.value:
            raise ValueError("cannot index a non-ready material")
        if vector_dimension < 1:
            raise ValueError("vector dimension must be positive")
        version = MaterialIndexVersion(
            material_id=material.id,
            class_id=material.class_id,
            source_sha256=material.sha256,
            extraction_version=extraction_version,
            chunking_version=chunking_version,
            embedding_model=embedding_model,
            vector_dimension=vector_dimension,
            build_state=IndexVersionState.BUILDING.value,
        )
        session.add(version)
        session.flush()
        return version

    def add_chunk(
        self,
        session: Session,
        version: MaterialIndexVersion,
        *,
        ordinal: int,
        text: str,
        page: int | None = None,
        line_start: int | None = None,
        line_end: int | None = None,
        section_label: str | None = None,
    ) -> KnowledgeChunk:
        if version.build_state != IndexVersionState.BUILDING.value:
            raise ValueError("chunks may only be added to a building version")
        clean = text.strip()
        if not clean:
            raise ValueError("chunk text must not be empty")
        if (page is None) == (line_start is None or line_end is None):
            raise ValueError("chunk must have exactly one valid page or line locator")
        if page is not None and (page < 1 or line_start is not None or line_end is not None):
            raise ValueError("invalid page locator")
        if line_start is not None and (line_start < 1 or line_end is None or line_end < line_start):
            raise ValueError("invalid line locator")
        chunk = KnowledgeChunk(
            index_version_id=version.id,
            material_id=version.material_id,
            class_id=version.class_id,
            ordinal=ordinal,
            text=clean,
            normalized_text=normalize_search_text(clean),
            text_hash=sha256(clean.encode("utf-8")).hexdigest(),
            page=page,
            line_start=line_start,
            line_end=line_end,
            section_label=(section_label.strip()[:200] if section_label else None),
        )
        session.add(chunk)
        session.flush()
        return chunk

    def activate_version(
        self,
        session: Session,
        version_id: uuid.UUID,
        *,
        vector_ready: bool,
        completed_at: datetime | None = None,
    ) -> MaterialIndexVersion:
        version = session.get(MaterialIndexVersion, version_id)
        if version is None:
            raise ValueError("index version not found")
        count = session.scalar(
            select(KnowledgeChunk.id).where(KnowledgeChunk.index_version_id == version.id).limit(1)
        )
        if count is None:
            raise ValueError("cannot activate an empty index version")
        version.build_state = IndexVersionState.READY.value
        version.completed_at = completed_at or datetime.now(UTC)
        state = session.scalar(
            select(MaterialSearchState).where(
                MaterialSearchState.material_id == version.material_id
            )
        )
        if state is None or state.class_id != version.class_id:
            raise ValueError("search state missing or mismatched")
        state.active_version_id = version.id
        state.status = RetrievalState.SEARCHABLE.value
        state.error_code = None if vector_ready else "semantic_pending"
        session.flush()
        return version

    def mark_failed(
        self,
        session: Session,
        material_id: uuid.UUID,
        *,
        error_code: str,
        retry_at: datetime | None = None,
    ) -> MaterialSearchState | None:
        state = session.scalar(
            select(MaterialSearchState).where(MaterialSearchState.material_id == material_id)
        )
        if state is None:
            return None
        state.status = RetrievalState.FAILED.value
        state.error_code = error_code[:80]
        state.next_retry_at = retry_at
        session.flush()
        return state

    def active_chunks(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        chunk_ids: Iterable[uuid.UUID] | None = None,
    ) -> list[KnowledgeChunk]:
        conditions = [
            KnowledgeChunk.class_id == class_id,
            Material.class_id == class_id,
            Material.state == MaterialState.READY.value,
            MaterialSearchState.class_id == class_id,
            MaterialSearchState.status == RetrievalState.SEARCHABLE.value,
            MaterialSearchState.active_version_id == KnowledgeChunk.index_version_id,
            MaterialIndexVersion.id == KnowledgeChunk.index_version_id,
            MaterialIndexVersion.build_state == IndexVersionState.READY.value,
        ]
        if chunk_ids is not None:
            ids = list(chunk_ids)
            if not ids:
                return []
            conditions.append(KnowledgeChunk.id.in_(ids))
        statement = (
            select(KnowledgeChunk)
            .join(Material, Material.id == KnowledgeChunk.material_id)
            .join(MaterialSearchState, MaterialSearchState.material_id == Material.id)
            .join(MaterialIndexVersion, MaterialIndexVersion.id == KnowledgeChunk.index_version_id)
            .where(*conditions)
        )
        return list(session.scalars(statement).all())

    def keyword_search(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        question: str,
        limit: int,
    ) -> list[KnowledgeChunk]:
        terms = query_terms(question)
        if not terms:
            return []
        # PostgreSQL performs the bounded candidate scan through the trgm
        # index; Python repeats the documented normalization check below.
        conditions = [
            KnowledgeChunk.class_id == class_id,
            Material.class_id == class_id,
            Material.state == MaterialState.READY.value,
            MaterialSearchState.class_id == class_id,
            MaterialSearchState.status == RetrievalState.SEARCHABLE.value,
            MaterialSearchState.active_version_id == KnowledgeChunk.index_version_id,
            MaterialIndexVersion.id == KnowledgeChunk.index_version_id,
            MaterialIndexVersion.build_state == IndexVersionState.READY.value,
            or_(*(KnowledgeChunk.normalized_text.contains(term) for term in terms)),
        ]
        statement = (
            select(KnowledgeChunk)
            .join(Material, Material.id == KnowledgeChunk.material_id)
            .join(MaterialSearchState, MaterialSearchState.material_id == Material.id)
            .join(MaterialIndexVersion, MaterialIndexVersion.id == KnowledgeChunk.index_version_id)
            .where(*conditions)
            .order_by(KnowledgeChunk.material_id, KnowledgeChunk.ordinal, KnowledgeChunk.id)
            .limit(max(limit, limit * 3))
        )
        candidates = list(session.scalars(statement).all())
        matching = [
            chunk for chunk in candidates if any(term in chunk.normalized_text for term in terms)
        ]
        matching.sort(
            key=lambda chunk: (
                -sum(chunk.normalized_text.count(term) for term in terms),
                chunk.material_id.hex,
                chunk.ordinal,
                chunk.id.hex,
            )
        )
        return matching[:limit]

    def search_status(self, session: Session, material_id: uuid.UUID) -> str:
        state = session.scalar(
            select(MaterialSearchState.status).where(MaterialSearchState.material_id == material_id)
        )
        return str(state or RetrievalState.PENDING.value)

    def aggregate_status(self, session: Session, *, class_id: uuid.UUID) -> dict[str, int]:
        states = session.scalars(
            select(MaterialSearchState).where(MaterialSearchState.class_id == class_id)
        )
        result = {status.value: 0 for status in RetrievalState}
        for state in states:
            if state.status in result:
                result[state.status] += 1
        return result

    def delete_stale_versions(
        self, session: Session, *, material_id: uuid.UUID, active_version_id: uuid.UUID | None
    ) -> int:
        versions = list(
            session.scalars(
                select(MaterialIndexVersion).where(MaterialIndexVersion.material_id == material_id)
            )
        )
        removed = 0
        for version in versions:
            if active_version_id is None or version.id != active_version_id:
                session.delete(version)
                removed += 1
        session.flush()
        return removed
