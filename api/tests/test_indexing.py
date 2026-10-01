import hashlib
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from pydantic import SecretStr
from sqlalchemy import select

from campusclaw.application.indexing import IndexWorker, aggregate_index_status
from campusclaw.application.providers import ProviderFailure
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import (
    Base,
    Class,
    IndexJobState,
    KnowledgeChunk,
    Material,
    MaterialIndexJob,
    MaterialSearchState,
    MaterialState,
    RetrievalState,
    User,
    UserRole,
)
from campusclaw.persistence.database import Database
from campusclaw.persistence.knowledge import KnowledgeRepository


class FakeEmbeddings:
    def __init__(self, dimension: int, *, fail: bool = False) -> None:
        self.dimension = dimension
        self.fail = fail
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.fail:
            raise ProviderFailure("embedding_unavailable")
        return [[0.1] * self.dimension for _ in texts]


class FakeVectors:
    def __init__(self) -> None:
        self.ids: set[uuid.UUID] = set()
        self.ensure_calls = 0
        self.reconcile_calls = 0

    def ensure_collection(self) -> None:
        self.ensure_calls += 1

    def upsert(self, chunks: Iterable[KnowledgeChunk], vectors: Iterable[list[float]]) -> None:
        rows = list(chunks)
        assert len(rows) == len(list(vectors))
        self.ids.update(chunk.id for chunk in rows)

    def existing_ids(self, ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
        return set(ids) & self.ids

    def reconcile(
        self, expected: Iterable[KnowledgeChunk], *, class_id: uuid.UUID
    ) -> dict[str, int]:
        assert class_id
        self.reconcile_calls += 1
        rows = list(expected)
        expected_ids = {chunk.id for chunk in rows}
        return {
            "expected": len(rows),
            "missing": len(expected_ids - self.ids),
            "orphaned": 0,
            "deleted": 0,
        }


def make_settings(tmp_path: Path) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=f"sqlite+pysqlite:///{tmp_path / 'indexing.db'}",
        JWT_SIGNING_KEY=SecretStr("i" * 32),
        UPLOAD_ROOT=tmp_path / "materials",
        EMBEDDING_DIMENSION=4,
        EXTRACTION_CHUNK_CHARS=128,
        EXTRACTION_CHUNK_OVERLAP=16,
        EMBEDDING_BATCH_SIZE=2,
    )


def make_database(settings: Settings) -> Database:
    database = Database(settings.DATABASE_URL)
    Base.metadata.create_all(database.engine)
    return database


def add_material(
    database: Database,
    settings: Settings,
    *,
    data: bytes,
    filename: str = "lesson.txt",
    content_type: str = "text/plain",
    write_file: bool = True,
    state: str = MaterialState.READY.value,
) -> Material:
    class_id = uuid.uuid4()
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    storage_key = f"{class_id}/{material_id}/{filename}"
    if write_file:
        path = settings.UPLOAD_ROOT / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    material = Material(
        id=material_id,
        class_id=class_id,
        uploader_id=user_id,
        title="Lesson",
        original_filename=filename,
        content_type=content_type,
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=storage_key,
        state=state,
    )
    with database.transaction() as session:
        session.add(Class(id=class_id, name=f"Class-{class_id}"))
        session.add(
            User(
                id=user_id,
                account=f"user-{user_id}",
                password_hash="hash",
                role=UserRole.TEACHER.value,
                class_id=class_id,
            )
        )
        session.add(material)
    return material


def worker(
    database: Database,
    settings: Settings,
    embeddings: FakeEmbeddings,
    vectors: FakeVectors,
) -> IndexWorker:
    return IndexWorker(
        database,
        settings,
        embeddings=cast(Any, embeddings),
        vectors=cast(Any, vectors),
    )


def test_worker_indexes_reconciles_rebuilds_and_reports(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = make_database(settings)
    material = add_material(
        database,
        settings,
        data=("课程目标和考核要求。\n" * 40).encode(),
    )
    embeddings = FakeEmbeddings(settings.EMBEDDING_DIMENSION)
    vectors = FakeVectors()
    indexer = worker(database, settings, embeddings, vectors)

    assert indexer.enqueue_ready_material(material.id)
    results = indexer.run_until_empty(max_jobs=5)
    assert len(results) == 1
    assert results[0].status == RetrievalState.SEARCHABLE.value
    assert results[0].semantic_ready
    assert results[0].chunks > 1
    assert vectors.ensure_calls == 1

    with database.transaction() as session:
        chunks = list(
            session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.material_id == material.id))
        )
        job = session.scalar(select(MaterialIndexJob))
        state = session.scalar(select(MaterialSearchState))
        assert job is not None and job.state == IndexJobState.COMPLETE.value
        assert state is not None and state.status == RetrievalState.SEARCHABLE.value
    assert aggregate_index_status(database, material.class_id)["searchable"] == 1

    vectors.ids.clear()
    report = indexer.reconcile_class(material.class_id)
    assert report["repaired"] == len(chunks)
    assert vectors.reconcile_calls == 1
    assert indexer.rebuild_vectors() == len(chunks)
    assert indexer.backfill() == 1
    assert indexer.process_one() is None
    database.dispose()


def test_worker_handles_unsupported_missing_and_semantic_failure(tmp_path: Path) -> None:
    unsupported_settings = make_settings(tmp_path / "unsupported")
    unsupported_db = make_database(unsupported_settings)
    unsupported = add_material(
        unsupported_db,
        unsupported_settings,
        data=b"\x89PNG\r\n",
        filename="image.png",
        content_type="application/octet-stream",
    )
    unsupported_worker = worker(
        unsupported_db,
        unsupported_settings,
        FakeEmbeddings(4),
        FakeVectors(),
    )
    assert unsupported_worker.enqueue_ready_material(unsupported.id)
    result = unsupported_worker.process_one()
    assert result is not None
    assert result.status == RetrievalState.UNSUPPORTED.value
    unsupported_db.dispose()

    missing_settings = make_settings(tmp_path / "missing")
    missing_db = make_database(missing_settings)
    missing = add_material(
        missing_db,
        missing_settings,
        data=b"missing",
        write_file=False,
    )
    missing_worker = worker(missing_db, missing_settings, FakeEmbeddings(4), FakeVectors())
    assert missing_worker.enqueue_ready_material(missing.id)
    result = missing_worker.process_one()
    assert result is not None
    assert result.error_code == "source_missing"
    missing_db.dispose()

    degraded_settings = make_settings(tmp_path / "degraded")
    degraded_db = make_database(degraded_settings)
    degraded = add_material(
        degraded_db,
        degraded_settings,
        data="可进行关键词检索。".encode(),
    )
    degraded_embeddings = FakeEmbeddings(4, fail=True)
    degraded_vectors = FakeVectors()
    degraded_worker = worker(
        degraded_db,
        degraded_settings,
        degraded_embeddings,
        degraded_vectors,
    )
    assert degraded_worker.enqueue_ready_material(degraded.id)
    result = degraded_worker.process_one()
    assert result is not None
    assert result.status == RetrievalState.SEARCHABLE.value
    assert not result.semantic_ready
    assert result.error_code == "semantic_pending"

    with degraded_db.transaction() as session:
        chunks_before = list(
            session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.material_id == degraded.id)
                .order_by(KnowledgeChunk.ordinal)
            )
        )
        chunk_ids_before = [chunk.id for chunk in chunks_before]
        job = session.scalar(select(MaterialIndexJob))
        state = session.scalar(select(MaterialSearchState))
        assert job is not None and state is not None
        active_version_before = state.active_version_id
        job.next_retry_at = None

    degraded_embeddings.fail = False
    recovered = degraded_worker.process_one()
    assert recovered is not None and recovered.semantic_ready
    with degraded_db.transaction() as session:
        chunks_after = list(
            session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.material_id == degraded.id)
                .order_by(KnowledgeChunk.ordinal)
            )
        )
        job = session.scalar(select(MaterialIndexJob))
        state = session.scalar(select(MaterialSearchState))
        assert [chunk.id for chunk in chunks_after] == chunk_ids_before
        assert state is not None and state.active_version_id == active_version_before
        assert state.error_code is None and state.next_retry_at is None
        assert job is not None and job.state == IndexJobState.COMPLETE.value
        assert job.last_error_code is None
    assert degraded_vectors.ids == set(chunk_ids_before)
    degraded_db.dispose()


def test_enqueue_and_claim_reject_non_ready_material(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = make_database(settings)
    pending = add_material(
        database,
        settings,
        data=b"pending",
        state=MaterialState.PENDING.value,
    )
    indexer = worker(database, settings, FakeEmbeddings(4), FakeVectors())
    assert not indexer.enqueue_ready_material(uuid.uuid4())
    assert not indexer.enqueue_ready_material(pending.id)

    with database.transaction() as session:
        pending.state = MaterialState.READY.value
        merged = session.merge(pending)
        KnowledgeRepository().enqueue_job(session, merged)
    claimed = indexer.claim()
    assert claimed is not None
    assert claimed.material_id == pending.id
    database.dispose()
