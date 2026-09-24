# pyright: basic, reportMissingImports=false
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update

from campusclaw.api.dependencies import Principal, get_current_principal
from campusclaw.application.sessions import SessionService
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base, Class, User
from campusclaw.persistence.database import Database


def principal_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'principal.db'}")
    Base.metadata.create_all(database.engine)
    settings = Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=f"sqlite+pysqlite:///{tmp_path / 'principal.db'}",
        SESSION_HMAC_KEY=SecretStr("p" * 32),
        SESSION_COOKIE_SECURE=False,
        UPLOAD_ROOT=tmp_path / "uploads",
    )
    sessions = SessionService(b"p" * 32, 3600)
    app = FastAPI()
    app.state.settings = settings
    app.state.database = database
    app.state.session_service = sessions

    @app.get("/protected")
    def protected(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> dict[str, str]:
        return {"account": principal.account, "role": principal.role.value}

    class_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with database.transaction() as session:
        session.add(Class(id=class_id, name="Principal Class"))
        session.add(
            User(
                id=user_id,
                account="principal.user",
                password_hash="hash",
                role="student",
                class_id=class_id,
            )
        )
    return app, database, sessions, settings, user_id


def test_protected_api_returns_json_401_without_redirect(tmp_path: Path) -> None:
    app, database, _, _, _ = principal_app(tmp_path)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/protected")
    assert response.status_code == 401
    assert response.headers.get("location") is None
    assert response.json() == {
        "detail": {"code": "unauthenticated", "message": "Authentication required"}
    }
    database.dispose()


def test_valid_session_resolves_immutable_principal(tmp_path: Path) -> None:
    app, database, sessions, settings, user_id = principal_app(tmp_path)
    with database.transaction() as db:
        issued = sessions.issue(db, user_id)
    with TestClient(app) as client:
        client.cookies.set(settings.SESSION_COOKIE_NAME, issued.token)
        response = client.get("/protected")
    assert response.status_code == 200
    assert response.json() == {"account": "principal.user", "role": "student"}
    database.dispose()


def test_expired_inactive_unknown_and_invalid_class_are_rejected(tmp_path: Path) -> None:
    app, database, sessions, settings, user_id = principal_app(tmp_path)
    now = datetime.now(UTC)
    with database.transaction() as db:
        expired = sessions.issue(db, user_id, now=now - timedelta(hours=2))
        active = sessions.issue(db, user_id, now=now)

    with TestClient(app) as client:
        client.cookies.set(settings.SESSION_COOKIE_NAME, expired.token)
        assert client.get("/protected").status_code == 401
        client.cookies.set(settings.SESSION_COOKIE_NAME, "unknown")
        assert client.get("/protected").status_code == 401

        with database.transaction() as db:
            user = db.get(User, user_id)
            assert user is not None
            user.is_active = False
        client.cookies.set(settings.SESSION_COOKIE_NAME, active.token)
        assert client.get("/protected").status_code == 401

        with database.transaction() as db:
            user = db.get(User, user_id)
            assert user is not None
            user.is_active = True
            user.class_id = uuid.uuid4()
        assert client.get("/protected").status_code == 401

        with database.engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
            class_id = connection.scalar(select(Class.id))
            assert class_id is not None
            connection.execute(
                update(User).where(User.id == user_id).values(role="admin", class_id=class_id)
            )
        assert client.get("/protected").status_code == 401
    database.dispose()
