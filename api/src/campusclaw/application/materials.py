# pyright: basic, reportMissingImports=false
"""Material creation policy shared by upload workflows."""

import hashlib
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal
from campusclaw.application.storage import (
    StagedUpload,
    contained_storage_path,
    material_storage_key,
    sanitize_display_filename,
)
from campusclaw.domain.models import Material, MaterialState
from campusclaw.persistence.database import Database


@dataclass(frozen=True)
class ReconciliationResult:
    temporary_files_removed: int
    pending_rows_removed: int
    pending_files_removed: int


def reconcile_storage(
    database: Database,
    upload_root: Path,
    *,
    max_age: timedelta = timedelta(hours=1),
    now: datetime | None = None,
) -> ReconciliationResult:
    """Remove interrupted-upload debris while leaving ready materials untouched."""
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")
    root = upload_root.resolve()
    temporary_root = root / "tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    temporary_root = temporary_root.resolve()
    if not temporary_root.is_relative_to(root):
        raise ValueError("temporary storage escapes upload root")
    cutoff = (now or datetime.now(UTC)) - max_age
    removed_temporary = 0
    for candidate in temporary_root.iterdir():
        if not (candidate.is_file() or candidate.is_symlink()):
            continue
        modified_at = datetime.fromtimestamp(candidate.lstat().st_mtime, UTC)
        if modified_at < cutoff:
            candidate.unlink()
            removed_temporary += 1

    with database.transaction() as session:
        stale_pending = list(
            session.scalars(
                select(Material).where(
                    Material.state == MaterialState.PENDING.value,
                    Material.created_at < cutoff,
                )
            )
        )

    removed_rows = 0
    removed_pending_files = 0
    for material in stale_pending:
        try:
            final_path = contained_storage_path(root, material.storage_key)
            if final_path.exists() or final_path.is_symlink():
                final_path.unlink()
                removed_pending_files += 1
        except (OSError, ValueError):
            # Keep a row whose file cannot be safely removed for the next run.
            continue
        with database.transaction() as session:
            deleted = session.execute(delete(Material).where(Material.id == material.id))
            if deleted.rowcount:
                removed_rows += 1

    return ReconciliationResult(removed_temporary, removed_rows, removed_pending_files)


def persist_material_upload(
    database: Database,
    principal: Principal,
    *,
    staged: StagedUpload,
    upload_root: Path,
    title: str,
    original_filename: str,
    content_type: str,
) -> Material:
    """Publish a staged file using pending metadata and an atomic rename.

    The database and filesystem cannot share a transaction, so pending rows are
    invisible to normal reads until the final state transition commits. Every
    failure path removes both the file and the pending row where possible.
    """
    root = upload_root.resolve()
    temporary_root = (root / "tmp").resolve()
    staged_path = staged.temp_path.resolve()
    if not staged_path.is_relative_to(temporary_root):
        raise ValueError("staged upload is outside temporary storage")
    if not staged_path.is_file():
        raise ValueError("staged upload is missing")

    material: Material | None = None
    final_path: Path | None = None
    pending_committed = False
    published = False
    try:
        with database.transaction() as session:
            material = create_pending_material(
                session,
                principal,
                title=title,
                original_filename=original_filename,
                content_type=content_type,
                byte_size=staged.byte_size,
                sha256=staged.sha256,
            )
        pending_committed = True
        assert material is not None

        target_path = contained_storage_path(root, material.storage_key)
        final_path = target_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            raise FileExistsError("material storage key already exists")
        os.replace(staged_path, target_path)

        with database.transaction() as session:
            ready_material = session.scalar(
                select(Material).where(
                    Material.id == material.id,
                    Material.state == MaterialState.PENDING.value,
                )
            )
            if ready_material is None:
                raise RuntimeError("pending material row disappeared")
            ready_material.state = MaterialState.READY.value
            session.flush()
            material = ready_material
        published = True
        return material
    finally:
        if not published:
            staged_path.unlink(missing_ok=True)
            if final_path is not None:
                final_path.unlink(missing_ok=True)
            if pending_committed and material is not None:
                # Preserve the original upload error; startup reconciliation retries
                # this cleanup if the database is temporarily unavailable.
                with suppress(Exception), database.transaction() as session:
                    session.execute(delete(Material).where(Material.id == material.id))


def create_pending_material(
    session: Session,
    principal: Principal,
    *,
    title: str,
    original_filename: str,
    content_type: str,
    byte_size: int,
    sha256: str,
    requested_class_id: uuid.UUID | None = None,
) -> Material:
    """Create metadata using only the authenticated principal's ownership fields.

    ``requested_class_id`` is accepted so callers can safely ignore a forged client field;
    it is never used as an authority source.
    """
    del requested_class_id
    if principal.role.value != "teacher":
        raise PermissionError("only teachers can create materials")
    if not title.strip():
        raise ValueError("title must not be empty")
    if byte_size < 0 or len(sha256) != hashlib.sha256().digest_size * 2:
        raise ValueError("invalid material metadata")
    material_id = uuid.uuid4()
    material = Material(
        id=material_id,
        class_id=principal.class_id,
        uploader_id=principal.user_id,
        title=title.strip(),
        original_filename=sanitize_display_filename(original_filename),
        content_type=content_type,
        byte_size=byte_size,
        sha256=sha256,
        storage_key=material_storage_key(principal.class_id, material_id),
        state=MaterialState.PENDING.value,
    )
    session.add(material)
    session.flush()
    return material
