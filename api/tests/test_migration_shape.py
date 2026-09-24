# pyright: basic, reportMissingImports=false
from pathlib import Path


def test_initial_migration_documents_destructive_downgrade() -> None:
    migration = next((Path(__file__).parents[1] / "migrations" / "versions").glob("*_initial.py"))
    text = migration.read_text()
    assert "Downgrade is destructive" in text
    assert 'op.drop_table("classes")' in text
