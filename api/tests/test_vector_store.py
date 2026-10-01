import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import SecretStr

from campusclaw.application.vector import QdrantVectorStore, point_id
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import KnowledgeChunk


class FakeQdrant:
    def __init__(self, *, page_size: int | None = None) -> None:
        self.points: dict[str, SimpleNamespace] = {}
        self.created = False
        self.last_scroll_filter: object | None = None
        self.page_size = page_size
        self.scroll_calls = 0

    def get_collection(self, name: str) -> object:
        if not self.created:
            raise RuntimeError("missing")
        params = SimpleNamespace(size=2, distance="Cosine")
        return SimpleNamespace(config=SimpleNamespace(params=params))

    def create_collection(self, **kwargs: object) -> None:
        self.created = True

    def upsert(self, *, points: list[Any], **kwargs: object) -> None:
        for point in points:
            value = point
            self.points[str(value.id)] = SimpleNamespace(
                id=value.id, payload=value.payload, score=1.0
            )

    def query_points(self, **kwargs: object) -> object:
        return SimpleNamespace(points=list(self.points.values()))

    def retrieve(self, *, ids: list[str], **kwargs: object) -> list[object]:
        return [self.points[item] for item in ids if item in self.points]

    def scroll(self, **kwargs: object) -> tuple[list[object], int | None]:
        self.last_scroll_filter = kwargs.get("scroll_filter")
        self.scroll_calls += 1
        rows: list[object] = list(self.points.values())
        raw_offset = kwargs.get("offset")
        assert raw_offset is None or isinstance(raw_offset, int)
        start = raw_offset or 0
        page_size = self.page_size or len(rows) or 1
        stop = min(len(rows), start + page_size)
        return rows[start:stop], (stop if stop < len(rows) else None)

    def delete(self, *, points_selector: object, **kwargs: object) -> None:
        selector: Any = points_selector
        for item in selector.points:
            self.points.pop(str(item), None)

    def create_snapshot(self, **kwargs: object) -> object:
        return SimpleNamespace(name="snapshot-1")


def settings(tmp_path: Path) -> Settings:
    return Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL="postgresql+psycopg://test:test@db/test",
        JWT_SIGNING_KEY=SecretStr("v" * 32),
        UPLOAD_ROOT=tmp_path,
        EMBEDDING_DIMENSION=2,
    )


def chunk() -> KnowledgeChunk:
    return KnowledgeChunk(
        id=uuid.uuid4(),
        index_version_id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        ordinal=0,
        text="authoritative",
        normalized_text="authoritative",
        text_hash="a" * 64,
        line_start=1,
        line_end=1,
    )


def test_qdrant_points_are_same_id_and_identifier_only(tmp_path: Path) -> None:
    fake = FakeQdrant()
    store = QdrantVectorStore(settings(tmp_path), fake)
    item = chunk()
    store.ensure_collection()
    store.upsert([item], [[0.1, 0.2]])
    point = fake.points[point_id(item.id)]
    assert point.id == point_id(item.id)
    assert point.payload == {
        "class_id": str(item.class_id),
        "material_id": str(item.material_id),
        "index_version_id": str(item.index_version_id),
    }
    hits = store.search(class_id=item.class_id, vector=[0.1, 0.2], limit=5)
    assert hits[0].chunk_id == item.id
    assert store.existing_ids([item.id]) == {item.id}
    assert store.reconcile([item], class_id=item.class_id)["missing"] == 0
    assert fake.last_scroll_filter is not None
    assert store.create_snapshot() == "snapshot-1"


def test_reconciliation_reads_all_pages_and_removes_invalid_points(tmp_path: Path) -> None:
    fake = FakeQdrant(page_size=1)
    store = QdrantVectorStore(settings(tmp_path), fake)
    expected = chunk()
    orphan = chunk()
    store.upsert([expected, orphan], [[0.1, 0.2], [0.2, 0.1]])
    fake.points[point_id(expected.id)].payload = {
        "class_id": str(expected.class_id),
        "material_id": str(uuid.uuid4()),
        "index_version_id": str(expected.index_version_id),
    }

    report = store.reconcile([expected], class_id=expected.class_id)

    assert fake.scroll_calls == 2
    assert report == {"expected": 1, "missing": 1, "orphaned": 2, "deleted": 2}
    assert fake.points == {}
