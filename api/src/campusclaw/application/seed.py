# pyright: basic, reportMissingImports=false
"""Idempotent demo-data initialization."""

import hashlib
import os
import uuid
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from campusclaw.config import Settings
from campusclaw.domain.models import Class, Material, MaterialState, User, UserRole
from campusclaw.domain.security import PasswordService
from campusclaw.persistence.database import Database


@dataclass(frozen=True)
class SeedClass:
    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class SeedUser:
    id: uuid.UUID
    account: str
    role: UserRole
    class_id: uuid.UUID
    password_key: str


@dataclass(frozen=True)
class SeedMaterial:
    id: uuid.UUID
    title: str
    filename: str
    class_id: uuid.UUID
    uploader_id: uuid.UUID


ALPHA = SeedClass(uuid.UUID("10000000-0000-0000-0000-000000000001"), "Alpha Class")
BETA = SeedClass(uuid.UUID("10000000-0000-0000-0000-000000000002"), "Beta Class")
SEED_CLASSES = (ALPHA, BETA)
SEED_USERS = (
    SeedUser(
        uuid.UUID("20000000-0000-0000-0000-000000000011"),
        "teacher.alpha",
        UserRole.TEACHER,
        ALPHA.id,
        "alpha_teacher",
    ),
    SeedUser(
        uuid.UUID("20000000-0000-0000-0000-000000000012"),
        "student.alpha",
        UserRole.STUDENT,
        ALPHA.id,
        "alpha_student",
    ),
    SeedUser(
        uuid.UUID("20000000-0000-0000-0000-000000000021"),
        "teacher.beta",
        UserRole.TEACHER,
        BETA.id,
        "beta_teacher",
    ),
    SeedUser(
        uuid.UUID("20000000-0000-0000-0000-000000000022"),
        "student.beta",
        UserRole.STUDENT,
        BETA.id,
        "beta_student",
    ),
)
SEED_MATERIALS = (
    SeedMaterial(
        uuid.UUID("30000000-0000-0000-0000-000000000001"),
        "Alpha welcome",
        "alpha-welcome.txt",
        ALPHA.id,
        SEED_USERS[0].id,
    ),
    SeedMaterial(
        uuid.UUID("30000000-0000-0000-0000-000000000002"),
        "Beta welcome",
        "beta-welcome.txt",
        BETA.id,
        SEED_USERS[2].id,
    ),
)


@dataclass(frozen=True)
class SeedResult:
    enabled: bool
    classes: int
    users: int
    materials: int


def _ensure_class(session: Session, item: SeedClass) -> bool:
    matches = session.scalars(
        select(Class).where(or_(Class.id == item.id, Class.name == item.name))
    ).all()
    if not matches:
        session.add(Class(id=item.id, name=item.name))
        return True
    if len(matches) != 1 or matches[0].id != item.id or matches[0].name != item.name:
        raise ValueError(f"seed conflict for class {item.name}")
    return False


def _ensure_user(
    session: Session,
    item: SeedUser,
    password: str,
    password_service: PasswordService,
) -> bool:
    matches = session.scalars(
        select(User).where(or_(User.id == item.id, User.account == item.account))
    ).all()
    if not matches:
        session.add(
            User(
                id=item.id,
                account=item.account,
                password_hash=password_service.hash(password),
                role=item.role.value,
                class_id=item.class_id,
            )
        )
        return True
    user = matches[0]
    if (
        len(matches) != 1
        or user.id != item.id
        or user.account != item.account
        or user.role != item.role.value
        or user.class_id != item.class_id
    ):
        raise ValueError(f"seed conflict for account {item.account}")
    return False


def _material_bytes(filename: str) -> bytes:
    return files("campusclaw.seed_assets").joinpath(filename).read_bytes()


def _ensure_material(
    session: Session,
    item: SeedMaterial,
    upload_root: Path,
    created_files: list[Path],
) -> bool:
    data = _material_bytes(item.filename)
    digest = hashlib.sha256(data).hexdigest()
    storage_key = f"{item.class_id}/{item.id}"
    final_path = (upload_root / storage_key).resolve()
    root = upload_root.resolve()
    if not final_path.is_relative_to(root):
        raise ValueError("generated seed path escaped upload root")

    matches = session.scalars(
        select(Material).where(or_(Material.id == item.id, Material.storage_key == storage_key))
    ).all()
    if matches:
        material = matches[0]
        valid = (
            len(matches) == 1
            and material.id == item.id
            and material.class_id == item.class_id
            and material.uploader_id == item.uploader_id
            and material.storage_key == storage_key
            and material.state == MaterialState.READY.value
            and material.sha256 == digest
            and material.byte_size == len(data)
            and final_path.is_file()
            and hashlib.sha256(final_path.read_bytes()).hexdigest() == digest
        )
        if not valid:
            raise ValueError(f"seed conflict for material {item.title}")
        return False

    temp_dir = root / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"seed-{item.id}.tmp"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temp_path.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        material = Material(
            id=item.id,
            class_id=item.class_id,
            uploader_id=item.uploader_id,
            title=item.title,
            original_filename=item.filename,
            content_type="text/plain",
            byte_size=len(data),
            sha256=digest,
            storage_key=storage_key,
            state=MaterialState.PENDING.value,
        )
        session.add(material)
        session.flush()
        os.replace(temp_path, final_path)
        created_files.append(final_path)
        material.state = MaterialState.READY.value
        return True
    finally:
        temp_path.unlink(missing_ok=True)


def seed_demo(
    database: Database,
    settings: Settings,
    *,
    password_service: PasswordService | None = None,
    fault_after: str | None = None,
) -> SeedResult:
    """Seed stable demo records, preserving existing passwords and user data."""
    if not settings.SEED_DEMO_DATA:
        return SeedResult(False, 0, 0, 0)

    passwords = settings.require_seed_passwords()
    hasher = password_service or PasswordService()
    created_files: list[Path] = []
    created_classes = created_users = created_materials = 0
    try:
        with database.transaction() as session:
            for class_item in SEED_CLASSES:
                created_classes += _ensure_class(session, class_item)
            session.flush()
            for user_item in SEED_USERS:
                created_users += _ensure_user(
                    session,
                    user_item,
                    passwords[user_item.password_key].get_secret_value(),
                    hasher,
                )
            session.flush()
            for index, material_item in enumerate(SEED_MATERIALS):
                created_materials += _ensure_material(
                    session, material_item, settings.UPLOAD_ROOT, created_files
                )
                if fault_after == f"material-{index + 1}":
                    raise RuntimeError("injected seed failure")
        return SeedResult(True, created_classes, created_users, created_materials)
    except BaseException:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise
