# pyright: basic, reportMissingImports=false
from pathlib import Path


def test_migrations_document_destructive_session_removal() -> None:
    migrations = Path(__file__).parents[1] / "migrations" / "versions"
    initial = next(migrations.glob("*_initial.py")).read_text()
    jwt_migration = next(migrations.glob("*_replace_sessions_with_jwt.py")).read_text()
    assert "Downgrade is destructive" in initial
    assert 'op.drop_table("sessions")' in jwt_migration
    assert 'down_revision: str | None = "20260923_0001"' in jwt_migration


def test_agent_chat_migration_is_additive_and_keeps_the_processing_turn_partial_index() -> None:
    migrations = Path(__file__).parents[1] / "migrations" / "versions"
    migration = next(migrations.glob("*_add_agent_chat_persistence.py")).read_text()
    assert 'down_revision: str | Sequence[str] | None = "20260929_0003"' in migration
    for table_name in (
        "agents",
        "agent_revisions",
        "skills",
        "skill_revisions",
        "agent_skill_bindings",
        "conversations",
        "conversation_messages",
        "message_citations",
    ):
        assert f'op.create_table(\n        "{table_name}",' in migration
    assert '"uq_conversation_messages_processing_assistant"' in migration
    assert "postgresql_where=sa.text(\"role = 'assistant' AND state = 'processing'\")" in migration
