# pyright: basic, reportMissingImports=false
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base, Class, Session, User
from campusclaw.domain.security import PasswordService
from campusclaw.main import create_app
from campusclaw.persistence.database import Database


def authenticated_app(tmp_path: Path) -> tuple[TestClient, Database, Settings]:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'auth-session.db'}")
    Base.metadata.create_all(database.engine)
    hasher = PasswordService(memory_cost=8192, time_cost=1, parallelism=1)
    class_id = uuid.uuid4()
    with database.transaction() as session:
        session.add(Class(id=class_id, name="Auth Session Class"))
        session.add(
            User(
                account="student.session",
                password_hash=hasher.hash("student-secret"),
                role="student",
                class_id=class_id,
            )
        )
    settings = Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=f"sqlite+pysqlite:///{tmp_path / 'auth-session.db'}",
        SESSION_HMAC_KEY=SecretStr("a" * 32),
        SESSION_COOKIE_SECURE=False,
        UPLOAD_ROOT=tmp_path / "uploads",
    )
    return (
        TestClient(create_app(settings=settings, database=database, password_service=hasher)),
        database,
        settings,
    )


def test_me_returns_safe_identity_and_logout_revokes_session(tmp_path: Path) -> None:
    client, database, settings = authenticated_app(tmp_path)
    with client:
        login = client.post(
            "/api/auth/login",
            json={"account": "student.session", "password": "student-secret"},
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]

        identity = client.get("/api/auth/me")
        assert identity.status_code == 200
        assert identity.json()["account"] == "student.session"
        assert identity.json()["csrf_token"] == csrf
        assert not {"password", "password_hash"} & identity.json().keys()

        missing_csrf = client.post("/api/auth/logout", headers={"origin": "http://testserver"})
        assert missing_csrf.status_code == 403
        wrong_origin = client.post(
            "/api/auth/logout",
            headers={"origin": "https://attacker.invalid", "x-csrf-token": csrf},
        )
        assert wrong_origin.status_code == 403

        logout = client.post(
            "/api/auth/logout",
            headers={"origin": "http://testserver", "x-csrf-token": csrf},
        )
        assert logout.status_code == 204
        assert settings.SESSION_COOKIE_NAME not in client.cookies
        assert client.get("/api/auth/me").status_code == 401

    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Session)) == 0
    database.dispose()


def test_unauthenticated_logout_is_idempotent(tmp_path: Path) -> None:
    client, database, _ = authenticated_app(tmp_path)
    with client:
        first = client.post("/api/auth/logout")
        second = client.post("/api/auth/logout")
    assert first.status_code == second.status_code == 204
    database.dispose()
