"""Upgrade/backfill/downgrade only in a disposable, isolated PostgreSQL schema."""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.integration


def test_mcp_upgrade_backfills_legacy_revisions_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL is not configured")
    schema = f"test_mcp_migration_{uuid.uuid4().hex}"
    admin = create_engine(raw, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        driver = connection.connection.driver_connection
        assert driver is not None
        driver.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        driver.execute(
            sql.SQL("CREATE TABLE {}.alembic_version (version_num VARCHAR(32) PRIMARY KEY)").format(
                sql.Identifier(schema)
            )
        )
    url = make_url(raw).update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    try:
        command.upgrade(config, "20261015_0006")
        ids = {
            key: uuid.uuid4()
            for key in ["class", "user", "skill", "revision", "agent", "conversation", "message"]
        }
        metadata = MetaData()
        with engine.begin() as connection:
            classes = Table("classes", metadata, autoload_with=connection, schema=schema)
            users = Table("users", metadata, autoload_with=connection, schema=schema)
            skills = Table("skills", metadata, autoload_with=connection, schema=schema)
            revisions = Table("skill_revisions", metadata, autoload_with=connection, schema=schema)
            agents = Table("agents", metadata, autoload_with=connection, schema=schema)
            conversations = Table(
                "conversations", metadata, autoload_with=connection, schema=schema
            )
            messages = Table(
                "conversation_messages", metadata, autoload_with=connection, schema=schema
            )
            connection.execute(classes.insert().values(id=ids["class"], name="Retained class"))
            connection.execute(
                users.insert().values(
                    id=ids["user"],
                    account="retained",
                    password_hash="unchanged-hash",
                    role="teacher",
                    class_id=ids["class"],
                )
            )
            connection.execute(
                skills.insert().values(
                    id=ids["skill"],
                    class_id=ids["class"],
                    creator_id=ids["user"],
                )
            )
            connection.execute(
                revisions.insert().values(
                    id=ids["revision"],
                    skill_id=ids["skill"],
                    class_id=ids["class"],
                    creator_id=ids["user"],
                    revision_number=1,
                    name="Retained",
                    skill_type="solution_guidance",
                    instructions="Use hints",
                )
            )
            connection.execute(
                agents.insert().values(
                    id=ids["agent"],
                    class_id=ids["class"],
                    creator_id=ids["user"],
                )
            )
            connection.execute(
                conversations.insert().values(
                    id=ids["conversation"],
                    class_id=ids["class"],
                    student_id=ids["user"],
                    agent_id=ids["agent"],
                )
            )
            connection.execute(
                messages.insert().values(
                    id=ids["message"],
                    conversation_id=ids["conversation"],
                    class_id=ids["class"],
                    student_id=ids["user"],
                    agent_id=ids["agent"],
                    ordinal=1,
                    role="assistant",
                    state="completed",
                    content="retained answer",
                )
            )
        command.upgrade(config, "20261020_0007")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT tools FROM skill_revisions")) == [
                "knowledge_search"
            ]
            assert connection.scalar(text("SELECT tool_calls FROM conversation_messages")) == []
            assert (
                connection.scalar(text("SELECT content FROM conversation_messages"))
                == "retained answer"
            )
            assert (
                connection.scalar(text("SELECT instructions FROM skill_revisions")) == "Use hints"
            )
            assert connection.scalar(text("SELECT password_hash FROM users")) == "unchanged-hash"
        inspector = inspect(engine)
        assert {"mcp_servers", "mcp_discovered_tools", "mcp_tool_calls"} <= set(
            inspector.get_table_names(schema=schema)
        )
        assert {
            tuple(c["column_names"])
            for c in inspector.get_unique_constraints("mcp_servers", schema=schema)
        } >= {("class_id", "name")}
        assert {
            tuple(c["column_names"])
            for c in inspector.get_unique_constraints("mcp_tool_calls", schema=schema)
        } >= {("assistant_message_id", "tool_ref")}
        command.downgrade(config, "20261015_0006")
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT content FROM conversation_messages"))
                == "retained answer"
            )
        assert "tools" not in {
            c["name"] for c in inspect(engine).get_columns("skill_revisions", schema=schema)
        }
        command.upgrade(config, "20261020_0007")
    finally:
        engine.dispose()
        with admin.connect() as connection:
            driver = connection.connection.driver_connection
            assert driver is not None
            driver.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.dispose()
