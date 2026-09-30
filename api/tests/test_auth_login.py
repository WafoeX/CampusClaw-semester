import logging
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base, Class, User
from campusclaw.domain.security import PasswordService
from campusclaw.main import create_app
from campusclaw.persistence.database import Database

LoginContext = tuple[TestClient, Database]


@pytest.fixture
def login_context(tmp_path: Path) -> Iterator[LoginContext]:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'login.db'}")
    Base.metadata.create_all(database.engine)
    hasher = PasswordService(memory_cost=8192, time_cost=1, parallelism=1)
    class_id = uuid.uuid4()
    with database.transaction() as session:
        session.add(Class(id=class_id, name="Login Class"))
        session.add_all(
            [
                User(
                    account="teacher.login",
                    password_hash=hasher.hash("teacher-secret"),
                    role="teacher",
                    class_id=class_id,
                ),
                User(
                    account="student.login",
                    password_hash=hasher.hash("student-secret"),
                    role="student",
                    class_id=class_id,
                ),
            ]
        )
    settings = Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=f"sqlite+pysqlite:///{tmp_path / 'login.db'}",
        JWT_SIGNING_KEY=SecretStr("l" * 32),
        UPLOAD_ROOT=tmp_path / "uploads",
    )
    yield (
        TestClient(create_app(settings=settings, database=database, password_service=hasher)),
        database,
    )
    database.dispose()


@pytest.mark.parametrize(
    ("account", "password", "role"),
    [
        ("teacher.login", "teacher-secret", "teacher"),
        ("student.login", "student-secret", "student"),
    ],
)
def test_teacher_and_student_login_success(
    login_context: LoginContext, account: str, password: str, role: str
) -> None:
    client, database = login_context
    with client:
        response = client.post("/api/auth/login", json={"account": account, "password": password})
    assert response.status_code == 200
    body = response.json()
    assert body["account"] == account
    assert body["role"] == role
    assert body["token_type"] == "bearer"
    assert body["access_token"].count(".") == 2
    assert "set-cookie" not in response.headers
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 2


def test_unknown_and_wrong_password_have_identical_failure(
    login_context: LoginContext, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = login_context
    caplog.set_level(logging.DEBUG)
    with client:
        unknown = client.post(
            "/api/auth/login", json={"account": "unknown", "password": "do-not-log-me"}
        )
        wrong = client.post(
            "/api/auth/login", json={"account": "teacher.login", "password": "do-not-log-me"}
        )
    assert unknown.status_code == wrong.status_code == 401
    assert (
        unknown.json()
        == wrong.json()
        == {"detail": {"code": "invalid_credentials", "message": "Invalid account or password"}}
    )
    assert "do-not-log-me" not in caplog.text
