# pyright: basic, reportMissingImports=false
import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from campusclaw.api.dependencies import Principal
from campusclaw.application.materials import create_pending_material
from campusclaw.application.tokens import TokenService
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base, Class, Material, MaterialState, User, UserRole
from campusclaw.domain.security import PasswordService
from campusclaw.main import create_app
from campusclaw.persistence.database import Database


@pytest.fixture
def material_api(tmp_path: Path) -> Iterator[tuple[TestClient, Database, Settings, dict[str, str]]]:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'material-api.db'}")
    Base.metadata.create_all(database.engine)
    alpha_class, beta_class = uuid.uuid4(), uuid.uuid4()
    alpha_teacher, alpha_student, beta_teacher = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    material_id = uuid.UUID("50000000-0000-0000-0000-000000000001")
    created = datetime(2026, 1, 1, tzinfo=UTC)
    with database.transaction() as session:
        session.add_all(
            [
                Class(id=alpha_class, name="Alpha API Class"),
                Class(id=beta_class, name="Beta API Class"),
                User(
                    id=alpha_teacher,
                    account="teacher.api.alpha",
                    password_hash="hash",
                    role="teacher",
                    class_id=alpha_class,
                ),
                User(
                    id=alpha_student,
                    account="student.api.alpha",
                    password_hash="hash",
                    role="student",
                    class_id=alpha_class,
                ),
                User(
                    id=beta_teacher,
                    account="teacher.api.beta",
                    password_hash="hash",
                    role="teacher",
                    class_id=beta_class,
                ),
                Material(
                    id=material_id,
                    class_id=alpha_class,
                    uploader_id=alpha_teacher,
                    title="Alpha API material",
                    original_filename="alpha.txt",
                    content_type="text/plain",
                    byte_size=5,
                    sha256=hashlib.sha256(b"alpha").hexdigest(),
                    storage_key=f"{alpha_class}/{material_id}",
                    state=MaterialState.READY.value,
                    created_at=created,
                ),
            ]
        )
    settings = Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=f"sqlite+pysqlite:///{tmp_path / 'material-api.db'}",
        JWT_SIGNING_KEY=SecretStr("m" * 32),
        UPLOAD_ROOT=tmp_path / "uploads",
    )
    path = settings.UPLOAD_ROOT / f"{alpha_class}/{material_id}"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"alpha")
    hasher = PasswordService(memory_cost=8192, time_cost=1, parallelism=1)
    app = create_app(settings=settings, database=database, password_service=hasher)
    tokens = TokenService("m" * 32, 3600)
    with TestClient(app) as client:
        yield (
            client,
            database,
            settings,
            {
                "alpha_teacher": tokens.issue(alpha_teacher).token,
                "alpha_student": tokens.issue(alpha_student).token,
                "beta_teacher": tokens.issue(beta_teacher).token,
            },
        )
    database.dispose()


def authorization(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def test_teacher_upload_streams_metadata_and_bytes(
    material_api: tuple[TestClient, Database, Settings, dict[str, str]],
) -> None:
    client, database, settings, tokens = material_api
    response = client.post(
        "/api/materials",
        data={"title": "Uploaded lesson", "class_id": str(uuid.uuid4())},
        files={"file": (r"..\\lesson.txt", b"hello upload", "text/plain")},
        headers=authorization(tokens["alpha_teacher"]),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "lesson.txt"
    with database.transaction() as session:
        material = session.get(Material, uuid.UUID(body["id"]))
        assert material is not None
        uploader = session.get(User, material.uploader_id)
        assert uploader is not None
        assert material.class_id == uploader.class_id
        assert (settings.UPLOAD_ROOT / material.storage_key).read_bytes() == b"hello upload"


def test_student_upload_is_rejected_before_creating_metadata_or_files(
    material_api: tuple[TestClient, Database, Settings, dict[str, str]],
) -> None:
    client, database, settings, tokens = material_api
    response = client.post(
        "/api/materials",
        data={"title": "Student attempt"},
        files={"file": ("attempt.txt", b"not allowed", "text/plain")},
        headers=authorization(tokens["alpha_student"]),
    )
    assert response.status_code == 403
    with database.transaction() as session:
        assert session.scalar(select(Material).where(Material.title == "Student attempt")) is None
    assert list((settings.UPLOAD_ROOT / "tmp").iterdir()) == []


def test_upload_rejects_empty_title_and_oversized_file_without_partial_state(
    material_api: tuple[TestClient, Database, Settings, dict[str, str]],
) -> None:
    client, database, settings, tokens = material_api
    headers = authorization(tokens["alpha_teacher"])
    assert (
        client.post(
            "/api/materials",
            data={"title": "   "},
            files={"file": ("empty.txt", b"body")},
            headers=headers,
        ).status_code
        == 400
    )
    settings.UPLOAD_MAX_BYTES = 3
    assert (
        client.post(
            "/api/materials",
            data={"title": "Too large"},
            files={"file": ("large.txt", b"1234")},
            headers=headers,
        ).status_code
        == 413
    )
    with database.transaction() as session:
        assert (
            session.scalar(select(Material).where(Material.title.in_(["   ", "Too large"]))) is None
        )


def test_authorized_download_verifies_bytes_and_attachment_headers(
    material_api: tuple[TestClient, Database, Settings, dict[str, str]],
) -> None:
    client, _, _, tokens = material_api
    response = client.get(
        "/api/materials/50000000-0000-0000-0000-000000000001/download",
        headers=authorization(tokens["alpha_student"]),
    )
    assert response.status_code == 200
    assert response.content == b"alpha"
    assert "attachment" in response.headers["content-disposition"]


def test_download_missing_or_changed_file_never_returns_partial_success(
    material_api: tuple[TestClient, Database, Settings, dict[str, str]],
) -> None:
    client, _, settings, tokens = material_api
    next(settings.UPLOAD_ROOT.glob("*/*")).write_bytes(b"tampered")
    response = client.get(
        "/api/materials/50000000-0000-0000-0000-000000000001/download",
        headers=authorization(tokens["alpha_teacher"]),
    )
    assert response.status_code == 500
    assert b"alpha" not in response.content


def test_creation_uses_principal_class_and_uploader_not_client_selector(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'creation.db'}")
    Base.metadata.create_all(database.engine)
    alpha_class, beta_class, teacher_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with database.transaction() as session:
        session.add_all(
            [
                Class(id=alpha_class, name="Alpha"),
                Class(id=beta_class, name="Beta"),
                User(
                    id=teacher_id,
                    account="teacher.creation",
                    password_hash="hash",
                    role="teacher",
                    class_id=alpha_class,
                ),
            ]
        )
    principal = Principal(
        user_id=teacher_id, account="teacher.creation", role=UserRole.TEACHER, class_id=alpha_class
    )
    with database.transaction() as session:
        material = create_pending_material(
            session,
            principal,
            title="Created material",
            original_filename="../../outside.txt",
            content_type="text/plain",
            byte_size=5,
            sha256="a" * 64,
            requested_class_id=beta_class,
        )
        assert material.class_id == alpha_class
        assert material.uploader_id == teacher_id
    database.dispose()


def test_direct_api_access_is_authenticated_and_class_scoped(
    material_api: tuple[TestClient, Database, Settings, dict[str, str]],
) -> None:
    client, database, _, tokens = material_api
    material_id = "50000000-0000-0000-0000-000000000001"
    assert client.get("/api/materials").status_code == 401
    assert (
        client.get("/api/materials", headers=authorization(tokens["alpha_student"])).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/materials/{material_id}", headers=authorization(tokens["alpha_teacher"])
        ).status_code
        == 200
    )
    cross_class = client.get(
        f"/api/materials/{material_id}", headers=authorization(tokens["beta_teacher"])
    )
    missing = client.get(
        f"/api/materials/{uuid.uuid4()}", headers=authorization(tokens["beta_teacher"])
    )
    assert cross_class.status_code == missing.status_code == 404
    assert cross_class.json() == missing.json()
    database.dispose()
