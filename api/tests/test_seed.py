# pyright: basic, reportMissingImports=false
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from campusclaw.application.seed import SEED_USERS, seed_demo
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base, Class, Material, User
from campusclaw.domain.security import PasswordService
from campusclaw.persistence.database import Database


def seed_settings(upload_root: Path, suffix: str = "one") -> Settings:
    return Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SESSION_HMAC_KEY=SecretStr("s" * 32),
        SESSION_COOKIE_SECURE=False,
        UPLOAD_ROOT=upload_root,
        SEED_DEMO_DATA=True,
        DEMO_ALPHA_TEACHER_PASSWORD=SecretStr(f"alpha-teacher-{suffix}"),
        DEMO_ALPHA_STUDENT_PASSWORD=SecretStr(f"alpha-student-{suffix}"),
        DEMO_BETA_TEACHER_PASSWORD=SecretStr(f"beta-teacher-{suffix}"),
        DEMO_BETA_STUDENT_PASSWORD=SecretStr(f"beta-student-{suffix}"),
    )


def seed_database(path: Path) -> Database:
    database = Database(f"sqlite+pysqlite:///{path}")
    Base.metadata.create_all(database.engine)
    return database


def fast_hasher() -> PasswordService:
    return PasswordService(memory_cost=8192, time_cost=1, parallelism=1)


def counts(database: Database) -> tuple[int, int, int]:
    with database.transaction() as session:
        return (
            session.scalar(select(func.count()).select_from(Class)) or 0,
            session.scalar(select(func.count()).select_from(User)) or 0,
            session.scalar(select(func.count()).select_from(Material)) or 0,
        )


def test_seed_is_idempotent_and_never_resets_passwords(tmp_path: Path) -> None:
    database = seed_database(tmp_path / "seed.db")
    first = seed_demo(
        database,
        seed_settings(tmp_path / "uploads"),
        password_service=fast_hasher(),
    )
    assert (first.classes, first.users, first.materials) == (2, 4, 2)
    assert counts(database) == (2, 4, 2)
    with database.transaction() as session:
        original_hashes = dict(
            session.execute(select(User.account, User.password_hash)).tuples().all()
        )

    second = seed_demo(
        database,
        seed_settings(tmp_path / "uploads", "changed"),
        password_service=fast_hasher(),
    )
    assert (second.classes, second.users, second.materials) == (0, 0, 0)
    with database.transaction() as session:
        current_hashes = dict(
            session.execute(select(User.account, User.password_hash)).tuples().all()
        )
    assert current_hashes == original_hashes
    assert len([path for path in (tmp_path / "uploads").rglob("*") if path.is_file()]) == 2
    database.dispose()


def test_seed_conflicting_ownership_fails_visibly(tmp_path: Path) -> None:
    database = seed_database(tmp_path / "conflict.db")
    settings = seed_settings(tmp_path / "uploads")
    seed_demo(database, settings, password_service=fast_hasher())
    with database.transaction() as session:
        user = session.get(User, SEED_USERS[0].id)
        assert user is not None
        user.role = "student"
    with pytest.raises(ValueError, match="seed conflict for account"):
        seed_demo(database, settings, password_service=fast_hasher())
    database.dispose()


def test_seed_fault_rolls_back_rows_and_files(tmp_path: Path) -> None:
    database = seed_database(tmp_path / "fault.db")
    upload_root = tmp_path / "fault-uploads"
    with pytest.raises(RuntimeError, match="injected"):
        seed_demo(
            database,
            seed_settings(upload_root),
            password_service=fast_hasher(),
            fault_after="material-1",
        )
    assert counts(database) == (0, 0, 0)
    assert not [path for path in upload_root.rglob("*") if path.is_file()]
    database.dispose()


def test_disabled_seed_has_no_side_effects(tmp_path: Path, settings: Settings) -> None:
    database = seed_database(tmp_path / "disabled.db")
    result = seed_demo(database, settings)
    assert result.enabled is False
    assert counts(database) == (0, 0, 0)
    assert not settings.UPLOAD_ROOT.exists()
    database.dispose()
