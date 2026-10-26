"""Upgrade the existing agent/chat schema while preserving earlier application data."""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from psycopg import sql
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from campusclaw.domain.models import (
    Class,
    ConversationMessage,
    Material,
    MessageCitation,
    User,
)
from campusclaw.persistence.knowledge import KnowledgeRepository

pytestmark = pytest.mark.integration


def test_additive_snapshot_upgrade_preserves_existing_data(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    schema = f"test_snapshot_{uuid.uuid4().hex}"
    admin = create_engine(raw_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        driver = connection.connection.driver_connection
        assert driver is not None
        driver.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        # Prevent Alembic from seeing an unrelated public.alembic_version through
        # search_path and falsely treating this empty schema as already migrated.
        driver.execute(
            sql.SQL("CREATE TABLE {}.alembic_version (version_num VARCHAR(32) PRIMARY KEY)").format(
                sql.Identifier(schema)
            )
        )
    url = make_url(raw_url).update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    try:
        command.upgrade(config, "20260929_0003")
        class_id, user_id, material_id = (uuid.uuid4() for _ in range(3))
        with Session(engine) as session:
            session.add(Class(id=class_id, name="Retained class"))
            session.flush()
            session.add(
                User(
                    id=user_id,
                    account="retained.teacher",
                    password_hash="retained-hash",
                    role="teacher",
                    class_id=class_id,
                )
            )
            session.flush()
            session.add(
                Material(
                    id=material_id,
                    class_id=class_id,
                    uploader_id=user_id,
                    title="Retained material",
                    original_filename="retained.txt",
                    content_type="text/plain",
                    byte_size=10,
                    sha256="a" * 64,
                    storage_key="retained/file",
                    state="ready",
                )
            )
            session.flush()
            retained = session.get(Material, material_id)
            assert retained is not None
            repository = KnowledgeRepository()
            repository.enqueue_job(session, retained)
            version = repository.create_version(
                session, retained, embedding_model="retained-model", vector_dimension=8
            )
            chunk = repository.add_chunk(
                session,
                version,
                ordinal=0,
                text="retained indexed evidence",
                line_start=1,
                line_end=1,
            )
            repository.activate_version(session, version.id, vector_ready=False)
            retained_chunk_id, retained_version_id = chunk.id, version.id
            session.commit()
        before = set(inspect(engine).get_table_names(schema=schema))
        assert {"classes", "users", "materials", "knowledge_chunks"} <= before
        assert "agents" not in before
        command.upgrade(config, "head")
        after = set(inspect(engine).get_table_names(schema=schema))
        assert after - before == {
            "agents",
            "agent_revisions",
            "skills",
            "skill_revisions",
            "agent_skill_bindings",
            "conversations",
            "conversation_messages",
            "message_citations",
            "mcp_servers",
            "mcp_discovered_tools",
            "mcp_tool_calls",
        }
        with Session(engine) as session:
            user = session.get(User, user_id)
            material = session.get(Material, material_id)
            assert user is not None and user.password_hash == "retained-hash"
            assert user.class_id == class_id and user.role == "teacher"
            assert material is not None and material.sha256 == "a" * 64
            assert material.storage_key == "retained/file" and material.uploader_id == user_id
            chunks = KnowledgeRepository().active_chunks(session, class_id=class_id)
            assert len(chunks) == 1
            assert chunks[0].id == retained_chunk_id
            assert chunks[0].index_version_id == retained_version_id
            assert chunks[0].text == "retained indexed evidence"
            assert chunks[0].material_id == material_id
        snapshot = next(
            column
            for column in inspect(engine).get_columns("message_citations")
            if column["name"] == "source_snapshot"
        )
        assert snapshot["nullable"] is False
        with engine.connect() as connection:
            assert (
                connection.scalar(select(Class.name).where(Class.id == class_id))
                == "Retained class"
            )
            assert MigrationContext.configure(connection).get_current_revision() == "20261020_0007"
        notice = next(
            column
            for column in inspect(engine).get_columns("conversation_messages")
            if column["name"] == "configuration_updated"
        )
        assert notice["nullable"] is False
        assert {
            column["name"] for column in inspect(engine).get_columns("conversation_messages")
        } == {column.name for column in ConversationMessage.__table__.columns}
        assert {column["name"] for column in inspect(engine).get_columns("message_citations")} == {
            column.name for column in MessageCitation.__table__.columns
        }
    finally:
        engine.dispose()
        with admin.connect() as connection:
            driver = connection.connection.driver_connection
            assert driver is not None
            driver.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.dispose()
