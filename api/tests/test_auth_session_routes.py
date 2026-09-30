import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base, Class, User
from campusclaw.domain.security import PasswordService
from campusclaw.main import create_app
from campusclaw.persistence.database import Database


def authenticated_app(tmp_path: Path) -> tuple[TestClient, Database]:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'auth-token.db'}")
    Base.metadata.create_all(database.engine)
    hasher = PasswordService(memory_cost=8192, time_cost=1, parallelism=1)
    class_id = uuid.uuid4()
    with database.transaction() as session:
        session.add(Class(id=class_id, name="Auth Token Class"))
        session.add(
            User(
                account="student.token",
                password_hash=hasher.hash("student-secret"),
                role="student",
                class_id=class_id,
            )
        )
    settings = Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=f"sqlite+pysqlite:///{tmp_path / 'auth-token.db'}",
        JWT_SIGNING_KEY=SecretStr("a" * 32),
        UPLOAD_ROOT=tmp_path / "uploads",
    )
    return TestClient(
        create_app(settings=settings, database=database, password_service=hasher)
    ), database


def authorization(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def test_me_requires_bearer_token_and_logout_is_idempotent(tmp_path: Path) -> None:
    client, database = authenticated_app(tmp_path)
    with client:
        login = client.post(
            "/api/auth/login", json={"account": "student.token", "password": "student-secret"}
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        identity = client.get("/api/auth/me", headers=authorization(token))
        assert identity.status_code == 200
        assert identity.json()["account"] == "student.token"
        assert not {"password", "password_hash", "access_token"} & identity.json().keys()
        assert client.get("/api/auth/me").status_code == 401
        assert client.post("/api/auth/logout", headers=authorization(token)).status_code == 204
        assert client.post("/api/auth/logout").status_code == 204
        # JWT logout has no server-side revocation; client-side storage removal is authoritative.
        assert client.get("/api/auth/me", headers=authorization(token)).status_code == 200
    database.dispose()
