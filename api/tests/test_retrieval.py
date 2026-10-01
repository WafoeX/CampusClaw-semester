import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr

from campusclaw.application.providers import ProviderFailure
from campusclaw.application.retrieval import RetrievalService, VectorModeUnavailable
from campusclaw.application.vector import VectorHit
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import KnowledgeChunk


def make_chunk(ordinal: int) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=uuid.uuid4(),
        index_version_id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        ordinal=ordinal,
        text=f"课程片段 {ordinal}",
        normalized_text=f"课程片段 {ordinal}",
        text_hash=f"{ordinal:x}".rjust(64, "0"),
        line_start=ordinal + 1,
        line_end=ordinal + 1,
    )


class FakeRepository:
    def __init__(self, keyword: list[KnowledgeChunk], active: list[KnowledgeChunk]) -> None:
        self.keyword = keyword
        self.active = active

    def keyword_search(self, *_: Any, **kwargs: Any) -> list[KnowledgeChunk]:
        return self.keyword[: int(kwargs["limit"])]

    def active_chunks(self, *_: Any, **kwargs: Any) -> list[KnowledgeChunk]:
        ids = set(kwargs["chunk_ids"])
        return [chunk for chunk in self.active if chunk.id in ids]


class FakeEmbeddings:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def embed_one(self, text: str) -> list[float]:
        self.calls += 1
        if self.fail:
            raise ProviderFailure("embedding_unavailable")
        return [0.1, 0.2]


class FakeVectors:
    def __init__(self, chunks: list[KnowledgeChunk]) -> None:
        self.chunks = chunks

    def search(self, **_: Any) -> list[VectorHit]:
        return [VectorHit(chunk.id, 1.0 - index / 10) for index, chunk in enumerate(self.chunks)]


def settings() -> Settings:
    return Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL="postgresql+psycopg://test:test@db/test",
        JWT_SIGNING_KEY=SecretStr("r" * 32),
        UPLOAD_ROOT=Path("/tmp/retrieval-test"),
        EMBEDDING_DIMENSION=2,
        QUERY_DEFAULT_RESULT_LIMIT=2,
        QUERY_MAX_RESULT_LIMIT=3,
        QUERY_MAX_CANDIDATES=9,
    )


def service(
    repository: FakeRepository,
    embeddings: FakeEmbeddings,
    vectors: FakeVectors,
) -> RetrievalService:
    return RetrievalService(
        settings(),
        repository=cast(Any, repository),
        embeddings=cast(Any, embeddings),
        vectors=cast(Any, vectors),
    )


def test_keyword_vector_and_hybrid_modes_are_bounded() -> None:
    first, second, third = make_chunk(1), make_chunk(2), make_chunk(3)
    repository = FakeRepository([first, second, third], [third, second, first])
    embeddings = FakeEmbeddings()
    retrieval = service(repository, embeddings, FakeVectors([third, second]))
    class_id = uuid.uuid4()

    keyword = retrieval.retrieve(
        cast(Any, object()), class_id=class_id, question="课程", mode="keyword"
    )
    assert keyword.effective_mode == "keyword"
    assert keyword.chunks == [first, second]
    assert embeddings.calls == 0

    vector = retrieval.retrieve(
        cast(Any, object()),
        class_id=class_id,
        question="课程",
        mode="vector",
        result_limit=1,
    )
    assert vector.effective_mode == "vector"
    assert vector.chunks == [third]

    hybrid = retrieval.retrieve(
        cast(Any, object()),
        class_id=class_id,
        question="课程",
        mode="hybrid",
        result_limit=3,
    )
    assert hybrid.effective_mode == "hybrid"
    assert set(hybrid.chunks) == {first, second, third}


def test_vector_failure_is_explicit_or_safely_degraded() -> None:
    chunk = make_chunk(1)
    retrieval = service(
        FakeRepository([chunk], [chunk]), FakeEmbeddings(fail=True), FakeVectors([chunk])
    )
    class_id = uuid.uuid4()

    with pytest.raises(VectorModeUnavailable, match="vector_unavailable"):
        retrieval.retrieve(cast(Any, object()), class_id=class_id, question="课程", mode="vector")

    degraded = retrieval.retrieve(
        cast(Any, object()), class_id=class_id, question="课程", mode="hybrid"
    )
    assert degraded.effective_mode == "keyword_only"
    assert degraded.degraded
    assert degraded.chunks == [chunk]


def test_invalid_question_and_mode_fail_before_retrieval() -> None:
    repository = FakeRepository([], [])
    embeddings = FakeEmbeddings()
    retrieval = service(repository, embeddings, FakeVectors([]))
    class_id = uuid.uuid4()

    with pytest.raises(ValueError, match="invalid_question"):
        retrieval.retrieve(cast(Any, object()), class_id=class_id, question=" ", mode="hybrid")
    with pytest.raises(ValueError, match="invalid_retrieval_mode"):
        retrieval.retrieve(
            cast(Any, object()),
            class_id=class_id,
            question="课程",
            mode=cast(Any, "global"),
        )
    assert embeddings.calls == 0
