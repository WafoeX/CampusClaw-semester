# pyright: basic, reportMissingImports=false
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from campusclaw.domain.models import Base, Class, Material, MaterialState, User
from campusclaw.persistence.materials import MaterialRepository


def repository_session(
    tmp_path: Path,
) -> tuple[Session, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'materials.db'}")
    Base.metadata.create_all(engine)
    alpha_id, beta_id = uuid.uuid4(), uuid.uuid4()
    alpha_user, beta_user = uuid.uuid4(), uuid.uuid4()
    created = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        session.add_all(
            [
                Class(id=alpha_id, name="Alpha Repository Class"),
                Class(id=beta_id, name="Beta Repository Class"),
                User(
                    id=alpha_user,
                    account="teacher.repo.alpha",
                    password_hash="hash",
                    role="teacher",
                    class_id=alpha_id,
                ),
                User(
                    id=beta_user,
                    account="teacher.repo.beta",
                    password_hash="hash",
                    role="teacher",
                    class_id=beta_id,
                ),
                Material(
                    id=uuid.UUID("40000000-0000-0000-0000-000000000001"),
                    class_id=alpha_id,
                    uploader_id=alpha_user,
                    title="Alpha ready",
                    original_filename="alpha.txt",
                    content_type="text/plain",
                    byte_size=5,
                    sha256="a" * 64,
                    storage_key=f"{alpha_id}/alpha",
                    state=MaterialState.READY.value,
                    created_at=created,
                ),
                Material(
                    id=uuid.UUID("40000000-0000-0000-0000-000000000002"),
                    class_id=beta_id,
                    uploader_id=beta_user,
                    title="Beta ready",
                    original_filename="beta.txt",
                    content_type="text/plain",
                    byte_size=4,
                    sha256="b" * 64,
                    storage_key=f"{beta_id}/beta",
                    state=MaterialState.READY.value,
                    created_at=created + timedelta(seconds=1),
                ),
                Material(
                    id=uuid.UUID("40000000-0000-0000-0000-000000000004"),
                    class_id=alpha_id,
                    uploader_id=alpha_user,
                    title="Alpha same-time newer id",
                    original_filename="same-time.txt",
                    content_type="text/plain",
                    byte_size=9,
                    sha256="d" * 64,
                    storage_key=f"{alpha_id}/same-time",
                    state=MaterialState.READY.value,
                    created_at=created,
                ),
                Material(
                    id=uuid.UUID("40000000-0000-0000-0000-000000000003"),
                    class_id=alpha_id,
                    uploader_id=alpha_user,
                    title="Alpha pending",
                    original_filename="pending.txt",
                    content_type="text/plain",
                    byte_size=7,
                    sha256="c" * 64,
                    storage_key=f"{alpha_id}/pending",
                    state=MaterialState.PENDING.value,
                    created_at=created + timedelta(seconds=2),
                ),
            ]
        )
        session.commit()
    return Session(engine), alpha_id, beta_id, alpha_user, beta_user


def test_all_material_reads_require_and_apply_class_id(tmp_path: Path) -> None:
    session, alpha_id, beta_id, _, _ = repository_session(tmp_path)
    repository = MaterialRepository()
    alpha_material = uuid.UUID("40000000-0000-0000-0000-000000000001")
    beta_material = uuid.UUID("40000000-0000-0000-0000-000000000002")

    assert [item.title for item in repository.list_ready(session, alpha_id)] == [
        "Alpha same-time newer id",
        "Alpha ready",
    ]
    alpha_record = repository.get_metadata(session, alpha_id, alpha_material)
    assert alpha_record is not None
    assert alpha_record.title == "Alpha ready"
    assert repository.get_metadata(session, alpha_id, beta_material) is None
    assert repository.get_for_download(session, alpha_id, beta_material) is None
    beta_record = repository.get_for_download(session, beta_id, beta_material)
    assert beta_record is not None
    assert beta_record.title == "Beta ready"
    session.close()
