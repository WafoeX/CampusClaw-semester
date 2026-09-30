# pyright: basic, reportMissingImports=false

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Column, MetaData, String, Table, insert
from sqlalchemy.engine import Engine

from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import Base
from campusclaw.main import create_app
from campusclaw.persistence.database import Database


def settings_for(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL=database_url,
        JWT_SIGNING_KEY=SecretStr("h" * 32),
        UPLOAD_ROOT=tmp_path / "materials",
    )


def add_head(engine: Engine) -> None:
    metadata = MetaData()
    versions = Table(
        "alembic_version",
        metadata,
        Column("version_num", String(32), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(versions).values(version_num="20260929_0002"))


def test_health_reports_ready_only_after_database_head_and_storage_are_ready(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'health.db'}")
    Base.metadata.create_all(database.engine)
    add_head(database.engine)
    settings = settings_for(tmp_path, f"sqlite+pysqlite:///{tmp_path / 'health.db'}")

    with TestClient(create_app(settings=settings, database=database)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    database.dispose()


def test_health_is_unavailable_when_migration_head_is_missing(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'health.db'}")
    Base.metadata.create_all(database.engine)
    settings = settings_for(tmp_path, f"sqlite+pysqlite:///{tmp_path / 'health.db'}")

    with TestClient(create_app(settings=settings, database=database)) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["detail"] == {"status": "unavailable", "code": "not_ready"}
    database.dispose()


def test_health_is_unavailable_when_storage_is_not_a_directory(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'health.db'}")
    Base.metadata.create_all(database.engine)
    add_head(database.engine)
    storage_file = tmp_path / "materials-file"
    storage_file.write_text("not a directory")
    settings = settings_for(tmp_path, f"sqlite+pysqlite:///{tmp_path / 'health.db'}")
    settings.UPLOAD_ROOT = storage_file

    with TestClient(create_app(settings=settings, database=database)) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert "JWT_SIGNING_KEY" not in response.text
    database.dispose()
