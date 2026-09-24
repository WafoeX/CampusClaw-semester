# pyright: basic, reportMissingImports=false
import os

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, func, select
from sqlalchemy.orm import Session

from campusclaw.persistence.database import Database


def transaction_table(database_url: str) -> tuple[Database, Table]:
    database = Database(database_url)
    metadata = MetaData()
    records = Table("transaction_records", metadata, Column("id", Integer, primary_key=True))
    metadata.drop_all(database.engine, checkfirst=True)
    metadata.create_all(database.engine)
    return database, records


def test_transaction_commits_and_rolls_back_forced_exception() -> None:
    database, records = transaction_table("sqlite+pysqlite:///:memory:")
    with database.transaction() as session:
        session.execute(records.insert().values(id=1))

    with pytest.raises(RuntimeError, match="forced"), database.transaction() as session:
        session.execute(records.insert().values(id=2))
        raise RuntimeError("forced")

    with Session(database.engine) as session:
        assert session.scalar(select(func.count()).select_from(records)) == 1
    database.dispose()


@pytest.mark.integration
def test_postgresql_transaction_rollback() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    assert database_url is not None
    database, records = transaction_table(database_url)
    with pytest.raises(RuntimeError, match="forced"), database.transaction() as session:
        session.execute(records.insert().values(id=1))
        raise RuntimeError("forced")
    with Session(database.engine) as session:
        assert session.scalar(select(func.count()).select_from(records)) == 0
    database.dispose()
