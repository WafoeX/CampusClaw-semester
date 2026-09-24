# pyright: basic, reportMissingImports=false
"""SQLAlchemy engine, session, and explicit transaction ownership."""

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Own the engine and construct short-lived synchronous sessions."""

    def __init__(self, database_url: str, *, pool_pre_ping: bool = True) -> None:
        self.engine: Engine = create_engine(database_url, pool_pre_ping=pool_pre_ping)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Commit exactly once on success and roll back every exception."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def dependency(self) -> Generator[Session, None, None]:
        """Yield a request session; route/application services own commits."""
        session = self.session_factory()
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
