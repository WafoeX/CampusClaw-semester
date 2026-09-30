# pyright: basic, reportMissingImports=false
from pathlib import Path


def test_migrations_document_destructive_session_removal() -> None:
    migrations = Path(__file__).parents[1] / "migrations" / "versions"
    initial = next(migrations.glob("*_initial.py")).read_text()
    jwt_migration = next(migrations.glob("*_replace_sessions_with_jwt.py")).read_text()
    assert "Downgrade is destructive" in initial
    assert 'op.drop_table("sessions")' in jwt_migration
    assert 'down_revision: str | None = "20260923_0001"' in jwt_migration
