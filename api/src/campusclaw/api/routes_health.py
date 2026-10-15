# pyright: basic, reportMissingImports=false
"""Unauthenticated readiness endpoint."""

import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Column, MetaData, String, Table, select
from sqlalchemy.exc import SQLAlchemyError

from campusclaw.api.dependencies import get_database, get_settings
from campusclaw.config import Settings
from campusclaw.persistence.database import Database

EXPECTED_ALEMBIC_HEAD = "20261015_0006"
LEGACY_ALEMBIC_HEAD = "20260929_0002"
_READY_HEADS = {LEGACY_ALEMBIC_HEAD, "20260929_0003", EXPECTED_ALEMBIC_HEAD}
_ALEMBIC_VERSION = MetaData()
_ALEMBIC_VERSION_TABLE = Table(
    "alembic_version",
    _ALEMBIC_VERSION,
    Column("version_num", String, nullable=False),
)
router = APIRouter(tags=["health"])


def _database_version(database: Database) -> str | None:
    with database.engine.connect() as connection:
        connection.execute(select(1))
        return connection.scalar(select(_ALEMBIC_VERSION_TABLE.c.version_num))


def _database_is_ready(database: Database) -> bool:
    return _database_version(database) in _READY_HEADS


def _storage_is_ready(root: Path) -> bool:
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        return False
    descriptor, temporary_name = tempfile.mkstemp(prefix=".health-", dir=root)
    try:
        os.write(descriptor, b"ready")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
        Path(temporary_name).unlink(missing_ok=True)
    return True


@router.get("/health")
def health(
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    try:
        version = _database_version(database)
        if version not in _READY_HEADS or not _storage_is_ready(settings.UPLOAD_ROOT):
            raise RuntimeError("readiness dependency unavailable")
    except (OSError, SQLAlchemyError, RuntimeError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unavailable", "code": "not_ready"},
        ) from None
    if version == LEGACY_ALEMBIC_HEAD:
        return {"status": "ok"}
    return {
        "status": "ok",
        "retrieval_schema": "ready",
        "indexer": "ready",
        "qdrant": "configured",
        "embedding": "configured" if settings.EMBEDDING_ENDPOINT else "degraded",
        "generation": "configured" if settings.GENERATION_ENDPOINT else "degraded",
    }
