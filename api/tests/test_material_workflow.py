# pyright: basic, reportMissingImports=false

import os
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import select

from campusclaw.api.dependencies import Principal
from campusclaw.application.materials import persist_material_upload, reconcile_storage
from campusclaw.application.storage import stage_upload
from campusclaw.domain.models import Base, Class, Material, MaterialState, User, UserRole
from campusclaw.persistence.database import Database


def workflow_fixture(tmp_path: Path) -> tuple[Database, Principal, Path]:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'workflow.db'}")
    Base.metadata.create_all(database.engine)
    class_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with database.transaction() as session:
        session.add(Class(id=class_id, name="Workflow Class"))
        session.add(
            User(
                id=user_id,
                account="teacher.workflow",
                password_hash="hash",
                role=UserRole.TEACHER.value,
                class_id=class_id,
            )
        )
    principal = Principal(
        user_id=user_id,
        account="teacher.workflow",
        role=UserRole.TEACHER,
        class_id=class_id,
    )
    return database, principal, tmp_path / "uploads"


def test_persisted_material_is_visible_only_after_atomic_publish(tmp_path: Path) -> None:
    database, principal, upload_root = workflow_fixture(tmp_path)
    staged = stage_upload(BytesIO(b"complete material"), upload_root, 100)

    material = persist_material_upload(
        database,
        principal,
        staged=staged,
        upload_root=upload_root,
        title="Complete material",
        original_filename=r"..\lesson.txt",
        content_type="text/plain",
    )

    assert material.state == MaterialState.READY.value
    assert material.original_filename == "lesson.txt"
    assert not staged.temp_path.exists()
    final_path = upload_root / material.storage_key
    assert final_path.read_bytes() == b"complete material"
    with database.transaction() as session:
        rows = list(session.scalars(select(Material)))
        assert len(rows) == 1
        assert rows[0].state == MaterialState.READY.value
    database.dispose()


def test_reconciliation_removes_stale_interrupted_state_but_not_ready_files(tmp_path: Path) -> None:
    database, principal, upload_root = workflow_fixture(tmp_path)
    old = datetime(2020, 1, 1, tzinfo=UTC)
    ready_id = uuid.uuid4()
    pending_id = uuid.uuid4()
    with database.transaction() as session:
        session.add_all(
            [
                Material(
                    id=ready_id,
                    class_id=principal.class_id,
                    uploader_id=principal.user_id,
                    title="Ready",
                    original_filename="ready.txt",
                    content_type="text/plain",
                    byte_size=5,
                    sha256="a" * 64,
                    storage_key=f"{principal.class_id}/{ready_id}",
                    state=MaterialState.READY.value,
                    created_at=old,
                ),
                Material(
                    id=pending_id,
                    class_id=principal.class_id,
                    uploader_id=principal.user_id,
                    title="Pending",
                    original_filename="pending.txt",
                    content_type="text/plain",
                    byte_size=7,
                    sha256="b" * 64,
                    storage_key=f"{principal.class_id}/{pending_id}",
                    state=MaterialState.PENDING.value,
                    created_at=old,
                ),
            ]
        )
    ready_path = upload_root / f"{principal.class_id}/{ready_id}"
    pending_path = upload_root / f"{principal.class_id}/{pending_id}"
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    ready_path.write_bytes(b"ready")
    pending_path.write_bytes(b"pending")
    stale_temp = upload_root / "tmp" / "old.upload"
    stale_temp.parent.mkdir(parents=True, exist_ok=True)
    stale_temp.write_bytes(b"temporary")
    os.utime(stale_temp, (old.timestamp(), old.timestamp()))

    result = reconcile_storage(database, upload_root, max_age=timedelta(hours=1))

    assert result.temporary_files_removed == 1
    assert result.pending_rows_removed == 1
    assert result.pending_files_removed == 1
    assert ready_path.read_bytes() == b"ready"
    assert not pending_path.exists()
    with database.transaction() as session:
        remaining = list(session.scalars(select(Material)))
        assert [item.id for item in remaining] == [ready_id]
    database.dispose()


def test_rename_failure_removes_pending_row_and_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, principal, upload_root = workflow_fixture(tmp_path)
    staged = stage_upload(BytesIO(b"will fail"), upload_root, 100)

    def fail_rename(source: str | bytes | Path, destination: str | bytes | Path) -> None:
        del source, destination
        raise RuntimeError("injected rename failure")

    monkeypatch.setattr("campusclaw.application.materials.os.replace", fail_rename)
    with pytest.raises(RuntimeError, match="injected rename failure"):
        persist_material_upload(
            database,
            principal,
            staged=staged,
            upload_root=upload_root,
            title="Failed material",
            original_filename="failed.txt",
            content_type="text/plain",
        )

    with database.transaction() as session:
        assert session.scalar(select(Material)) is None
    assert list((upload_root / "tmp").iterdir()) == []
    assert list(upload_root.glob("*/*")) == []
    database.dispose()
