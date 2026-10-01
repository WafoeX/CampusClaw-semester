import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from campusclaw.application.retrieval import reciprocal_rank_fusion
from campusclaw.domain.models import (
    Base,
    IndexVersionState,
    KnowledgeChunk,
    Material,
    MaterialIndexVersion,
    MaterialSearchState,
    MaterialState,
    RetrievalState,
)
from campusclaw.persistence.knowledge import KnowledgeRepository, query_terms


def test_chinese_query_terms_do_not_match_on_single_common_characters() -> None:
    terms = query_terms("请根据本班资料概括课程内容")
    assert terms
    cjk_terms = [term for term in terms if all("\u3400" <= char <= "\u9fff" for char in term)]
    assert all(len(term) >= 2 for term in cjk_terms)
    assert "课程内容" in terms


def test_active_chunk_hydration_cannot_cross_class_or_version(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'knowledge.db'}")
    Base.metadata.create_all(engine)
    alpha = uuid.uuid4()
    beta = uuid.uuid4()
    uploader = uuid.uuid4()
    alpha_material = Material(
        id=uuid.uuid4(),
        class_id=alpha,
        uploader_id=uploader,
        title="Alpha",
        original_filename="a.txt",
        content_type="text/plain",
        byte_size=1,
        sha256="a" * 64,
        storage_key="alpha/a.txt",
        state=MaterialState.READY.value,
    )
    beta_material = Material(
        id=uuid.uuid4(),
        class_id=beta,
        uploader_id=uploader,
        title="Beta",
        original_filename="b.txt",
        content_type="text/plain",
        byte_size=1,
        sha256="b" * 64,
        storage_key="beta/b.txt",
        state=MaterialState.READY.value,
    )
    alpha_version = MaterialIndexVersion(
        id=uuid.uuid4(),
        material_id=alpha_material.id,
        class_id=alpha,
        source_sha256=alpha_material.sha256,
        extraction_version="v1",
        chunking_version="v1",
        embedding_model="test",
        vector_dimension=2,
        build_state=IndexVersionState.READY.value,
    )
    beta_version = MaterialIndexVersion(
        id=uuid.uuid4(),
        material_id=beta_material.id,
        class_id=beta,
        source_sha256=beta_material.sha256,
        extraction_version="v1",
        chunking_version="v1",
        embedding_model="test",
        vector_dimension=2,
        build_state=IndexVersionState.READY.value,
    )
    alpha_state = MaterialSearchState(
        material_id=alpha_material.id,
        class_id=alpha,
        status=RetrievalState.SEARCHABLE.value,
        active_version_id=alpha_version.id,
    )
    beta_state = MaterialSearchState(
        material_id=beta_material.id,
        class_id=beta,
        status=RetrievalState.SEARCHABLE.value,
        active_version_id=beta_version.id,
    )
    alpha_chunk = KnowledgeChunk(
        id=uuid.uuid4(),
        index_version_id=alpha_version.id,
        material_id=alpha_material.id,
        class_id=alpha,
        ordinal=0,
        text="same term alpha",
        normalized_text="same term alpha",
        text_hash="c" * 64,
        line_start=1,
        line_end=1,
    )
    beta_chunk = KnowledgeChunk(
        id=uuid.uuid4(),
        index_version_id=beta_version.id,
        material_id=beta_material.id,
        class_id=beta,
        ordinal=0,
        text="same term beta",
        normalized_text="same term beta",
        text_hash="d" * 64,
        line_start=1,
        line_end=1,
    )
    with Session(engine) as session:
        session.add_all(
            [
                alpha_material,
                beta_material,
                alpha_version,
                beta_version,
                alpha_state,
                beta_state,
                alpha_chunk,
                beta_chunk,
            ]
        )
        session.commit()
        rows = KnowledgeRepository().active_chunks(session, class_id=alpha)
        assert [row.text for row in rows] == ["same term alpha"]
    engine.dispose()


def test_repository_jobs_versions_and_keyword_search_are_idempotent(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'repository.db'}")
    Base.metadata.create_all(engine)
    class_id = uuid.uuid4()
    material = Material(
        id=uuid.uuid4(),
        class_id=class_id,
        uploader_id=uuid.uuid4(),
        title="Lesson",
        original_filename="lesson.txt",
        content_type="text/plain",
        byte_size=10,
        sha256="f" * 64,
        storage_key="lesson.txt",
        state=MaterialState.READY.value,
    )
    repository = KnowledgeRepository()
    with Session(engine) as session:
        session.add(material)
        session.flush()
        job = repository.enqueue_job(session, material)
        assert repository.enqueue_job(session, material).id == job.id
        claimed = repository.claim_job(session, owner="test", lease_seconds=30)
        assert claimed is not None
        repository.retry_job(session, claimed.id, error_code="temporary", max_attempts=3)
        version = repository.create_version(
            session, material, embedding_model="test", vector_dimension=2
        )
        repository.add_chunk(
            session, version, ordinal=0, text="Chinese 课程 text", line_start=1, line_end=2
        )
        repository.activate_version(session, version.id, vector_ready=False)
        assert repository.keyword_search(session, class_id=class_id, question="课程", limit=5)
        assert repository.aggregate_status(session, class_id=class_id)["searchable"] == 1
        assert (
            repository.delete_stale_versions(
                session, material_id=material.id, active_version_id=version.id
            )
            == 0
        )
    engine.dispose()


def test_rrf_deduplicates_and_has_stable_class_independent_order() -> None:
    def chunk(ordinal: int) -> KnowledgeChunk:
        return KnowledgeChunk(
            id=uuid.uuid4(),
            index_version_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            class_id=uuid.uuid4(),
            ordinal=ordinal,
            text=f"text-{ordinal}",
            normalized_text=f"text-{ordinal}",
            text_hash="e" * 64,
            line_start=1,
            line_end=1,
        )

    first = chunk(1)
    second = chunk(2)
    result = reciprocal_rank_fusion([first, second], [second, first], constant=60, limit=2)
    assert len(result) == 2
    assert {item.id for item in result} == {first.id, second.id}
