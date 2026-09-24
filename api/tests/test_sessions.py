# pyright: basic, reportMissingImports=false
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, create_engine, func, select
from sqlalchemy.orm import Session as DatabaseSession

from campusclaw.application.sessions import SessionService
from campusclaw.domain.models import Base, Class, Session, User


def session_db(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'sessions.db'}")
    tables = [
        cast(Table, Class.__table__),
        cast(Table, User.__table__),
        cast(Table, Session.__table__),
    ]
    Base.metadata.create_all(engine, tables=tables)
    class_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with DatabaseSession(engine) as database:
        database.add(Class(id=class_id, name="Session Class"))
        database.add(
            User(
                id=user_id,
                account="session.user",
                password_hash="hash",
                role="student",
                class_id=class_id,
            )
        )
        database.commit()
    return engine, user_id


def test_issue_lookup_and_digest_only_persistence(tmp_path: Path) -> None:
    engine, user_id = session_db(tmp_path)
    service = SessionService(b"k" * 32, 3600)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with DatabaseSession(engine) as database:
        issued = service.issue(database, user_id, now=now)
        database.commit()
        record = database.scalar(select(Session))
        assert record is not None
        assert record.token_digest == service.digest(issued.token)
        assert record.csrf_digest == service.digest(issued.csrf_token)
        assert issued.token.encode() not in record.token_digest
        assert service.csrf_is_valid(record, issued.csrf_token)
        assert not service.csrf_is_valid(record, "wrong")
        assert not service.csrf_is_valid(record, None)
        assert service.resolve(database, issued.token, now=now + timedelta(minutes=1)) is record
    engine.dispose()


def test_expiry_revocation_and_cleanup(tmp_path: Path) -> None:
    engine, user_id = session_db(tmp_path)
    service = SessionService(b"k" * 32, 60)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with DatabaseSession(engine) as database:
        expired = service.issue(database, user_id, now=now)
        active = service.issue(database, user_id, now=now + timedelta(seconds=120))
        database.commit()
        assert service.resolve(database, expired.token, now=now + timedelta(seconds=61)) is None
        assert service.resolve(database, "unknown", now=now) is None
        assert service.revoke(database, active.token) is True
        assert service.revoke(database, active.token) is False
        database.commit()
        assert database.scalar(select(func.count()).select_from(Session)) == 0

        service.issue(database, user_id, now=now)
        service.issue(database, user_id, now=now + timedelta(seconds=120))
        database.commit()
        assert service.cleanup_expired(database, now=now + timedelta(seconds=61)) == 1
        database.commit()
        assert database.scalar(select(func.count()).select_from(Session)) == 1
    engine.dispose()


@pytest.mark.integration
def test_postgresql_session_lifecycle_and_digest_persistence() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    assert database_url is not None
    engine = create_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    class_id = uuid.uuid4()
    user_id = uuid.uuid4()
    service = SessionService(b"p" * 32, 60)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with DatabaseSession(engine) as database:
        database.add(Class(id=class_id, name="PostgreSQL Session Class"))
        database.add(
            User(
                id=user_id,
                account="postgres.session",
                password_hash="hash",
                role="teacher",
                class_id=class_id,
            )
        )
        database.flush()
        issued = service.issue(database, user_id, now=now)
        database.commit()
        record = database.scalar(select(Session))
        assert record is not None
        assert record.token_digest == service.digest(issued.token)
        assert issued.token.encode() not in record.token_digest
        assert service.resolve(database, issued.token, now=now + timedelta(seconds=61)) is None
        database.commit()
    engine.dispose()


def test_session_policy_rejects_weak_key_and_invalid_lifetime() -> None:
    try:
        SessionService(b"short", 60)
    except ValueError as error:
        assert "at least 32" in str(error)
    else:
        raise AssertionError("weak key accepted")

    try:
        SessionService(b"k" * 32, 0)
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("invalid lifetime accepted")
