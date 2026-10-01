# pyright: basic, reportMissingImports=false, reportMissingTypeStubs=false
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import create_engine, event

from campusclaw.application.seed import seed_demo  # pyright: ignore[reportMissingTypeStubs]
from campusclaw.config import AppEnvironment, Settings  # pyright: ignore[reportMissingTypeStubs]
from campusclaw.domain.models import Base  # pyright: ignore[reportMissingTypeStubs]
from campusclaw.domain.security import PasswordService  # pyright: ignore[reportMissingTypeStubs]
from campusclaw.main import create_app  # pyright: ignore[reportMissingTypeStubs]
from campusclaw.persistence.database import Database  # pyright: ignore[reportMissingTypeStubs]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL="postgresql+psycopg://test:test@db/test",
        JWT_SIGNING_KEY=SecretStr("t" * 32),
        UPLOAD_ROOT=tmp_path / "materials",
    )


@dataclass(frozen=True)
class PostgresApiFixture:
    """A per-test PostgreSQL API environment using the stable demo manifest."""

    app: FastAPI
    database: Database
    settings: Settings
    passwords: dict[str, str]

    def client(self) -> TestClient:
        """Create a client for independent Bearer-token authentication checks."""
        return TestClient(self.app)


@pytest.fixture
def postgres_api_fixture(tmp_path: Path) -> Iterator[PostgresApiFixture]:
    """Create an isolated PostgreSQL schema and seeded API, or skip without one."""
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    schema = f"test_api_{uuid.uuid4().hex}"
    admin_engine = create_engine(raw_url, isolation_level="AUTOCOMMIT")
    database: Database | None = None
    try:
        with admin_engine.connect() as connection:
            driver_connection = connection.connection.driver_connection
            assert driver_connection is not None
            driver_connection.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            driver_connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        database = Database(raw_url)

        @event.listens_for(database.engine, "connect")
        def set_test_search_path(dbapi_connection: Any, _: Any) -> None:
            with dbapi_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
                )

        Base.metadata.create_all(database.engine)
        passwords = {
            "alpha_teacher": uuid.uuid4().hex,
            "alpha_student": uuid.uuid4().hex,
            "beta_teacher": uuid.uuid4().hex,
            "beta_student": uuid.uuid4().hex,
        }
        settings = Settings(
            APP_ENV=AppEnvironment.TEST,
            DATABASE_URL=raw_url,
            JWT_SIGNING_KEY=SecretStr(uuid.uuid4().hex * 2),
            UPLOAD_ROOT=tmp_path / "materials",
            SEED_DEMO_DATA=True,
            DEMO_ALPHA_TEACHER_PASSWORD=SecretStr(passwords["alpha_teacher"]),
            DEMO_ALPHA_STUDENT_PASSWORD=SecretStr(passwords["alpha_student"]),
            DEMO_BETA_TEACHER_PASSWORD=SecretStr(passwords["beta_teacher"]),
            DEMO_BETA_STUDENT_PASSWORD=SecretStr(passwords["beta_student"]),
        )
        hasher = PasswordService(memory_cost=8192, time_cost=1, parallelism=1)
        seed_demo(database, settings, password_service=hasher)
        app = create_app(settings=settings, database=database, password_service=hasher)
        yield PostgresApiFixture(app, database, settings, passwords)
    finally:
        if database is not None:
            database.dispose()
        with admin_engine.connect() as connection:
            driver_connection = connection.connection.driver_connection
            assert driver_connection is not None
            driver_connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )
        admin_engine.dispose()
