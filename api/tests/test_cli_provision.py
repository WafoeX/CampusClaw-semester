# pyright: basic, reportMissingImports=false
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, create_engine, func, select
from sqlalchemy.orm import Session

from campusclaw.cli.main import provision_user
from campusclaw.domain.models import Base, Class, User, UserRole
from campusclaw.domain.security import PasswordService


@pytest.fixture
def session(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'provision.db'}")
    tables = [cast(Table, Class.__table__), cast(Table, User.__table__)]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_provision_teacher_and_student_without_plaintext_storage(session: Session) -> None:
    hasher = PasswordService(memory_cost=8192, time_cost=1, parallelism=1)
    teacher = provision_user(
        session,
        account="teacher.alpha",
        class_name="Alpha",
        role=UserRole.TEACHER,
        password="teacher-password",
        create_class=True,
        password_service=hasher,
    )
    session.commit()
    student = provision_user(
        session,
        account="student.alpha",
        class_name="Alpha",
        role=UserRole.STUDENT,
        password="student-password",
        create_class=False,
        password_service=hasher,
    )
    session.commit()

    assert session.scalar(select(func.count()).select_from(Class)) == 1
    assert teacher.class_id == student.class_id
    assert "teacher-password" not in teacher.password_hash
    assert "student-password" not in student.password_hash
    assert hasher.verify(teacher.password_hash, "teacher-password")


def test_provision_requires_existing_class_without_flag(session: Session) -> None:
    with pytest.raises(ValueError, match="class does not exist"):
        provision_user(
            session,
            account="student.missing",
            class_name="Missing",
            role=UserRole.STUDENT,
            password="password",
            create_class=False,
        )
    assert session.scalar(select(func.count()).select_from(User)) == 0
