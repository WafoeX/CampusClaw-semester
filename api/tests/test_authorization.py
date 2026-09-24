# pyright: basic, reportMissingImports=false
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from campusclaw.api.dependencies import Principal, require_teacher
from campusclaw.application.sessions import SessionService
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base, Class, User
from campusclaw.persistence.database import Database


def test_teacher_dependency_rejects_student_and_allows_teacher(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'authorization.db'}")
    Base.metadata.create_all(database.engine)
    class_id = uuid.uuid4()
    student_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    with database.transaction() as session:
        session.add(Class(id=class_id, name="Authorization Class"))
        session.add_all(
            [
                User(
                    id=student_id,
                    account="student.auth",
                    password_hash="hash",
                    role="student",
                    class_id=class_id,
                ),
                User(
                    id=teacher_id,
                    account="teacher.auth",
                    password_hash="hash",
                    role="teacher",
                    class_id=class_id,
                ),
            ]
        )
    settings = Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=f"sqlite+pysqlite:///{tmp_path / 'authorization.db'}",
        SESSION_HMAC_KEY=SecretStr("r" * 32),
        SESSION_COOKIE_SECURE=False,
        UPLOAD_ROOT=tmp_path / "uploads",
    )
    sessions = SessionService(b"r" * 32, 3600)
    app = FastAPI()
    app.state.settings = settings
    app.state.database = database
    app.state.session_service = sessions

    @app.get("/teacher-only")
    def teacher_only(principal: Annotated[Principal, Depends(require_teacher)]) -> dict[str, str]:
        return {"account": principal.account}

    with database.transaction() as session:
        student_session = sessions.issue(session, student_id)
        teacher_session = sessions.issue(session, teacher_id)
    with TestClient(app) as client:
        client.cookies.set(settings.SESSION_COOKIE_NAME, student_session.token)
        assert client.get("/teacher-only").status_code == 403
        client.cookies.set(settings.SESSION_COOKIE_NAME, teacher_session.token)
        response = client.get("/teacher-only")
        assert response.status_code == 200
        assert response.json() == {"account": "teacher.auth"}
    database.dispose()
