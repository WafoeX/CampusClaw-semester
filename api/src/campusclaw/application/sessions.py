# pyright: basic, reportMissingImports=false
"""Opaque server-side session lifecycle."""

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DatabaseSession

from campusclaw.domain.models import Session


@dataclass(frozen=True)
class IssuedSession:
    token: str
    csrf_token: str
    expires_at: datetime


class SessionService:
    """Create and resolve random tokens while persisting only HMAC digests."""

    def __init__(self, hmac_key: bytes, lifetime_seconds: int) -> None:
        if len(hmac_key) < 32:
            raise ValueError("session HMAC key must contain at least 32 bytes")
        if lifetime_seconds <= 0:
            raise ValueError("session lifetime must be positive")
        self._hmac_key = hmac_key
        self._lifetime = timedelta(seconds=lifetime_seconds)

    def digest(self, token: str) -> bytes:
        return hmac.new(self._hmac_key, token.encode("utf-8"), hashlib.sha256).digest()

    def csrf_token(self, session_token: str) -> str:
        raw = hmac.new(
            self._hmac_key,
            b"csrf:" + session_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def issue(
        self,
        database: DatabaseSession,
        user_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> IssuedSession:
        issued_at = now or datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        csrf_token = self.csrf_token(token)
        expires_at = issued_at + self._lifetime
        database.add(
            Session(
                token_digest=self.digest(token),
                csrf_digest=self.digest(csrf_token),
                user_id=user_id,
                expires_at=expires_at,
                created_at=issued_at,
                last_seen_at=issued_at,
            )
        )
        database.flush()
        return IssuedSession(token, csrf_token, expires_at)

    def resolve(
        self,
        database: DatabaseSession,
        token: str,
        *,
        now: datetime | None = None,
    ) -> Session | None:
        current_time = now or datetime.now(UTC)
        record = database.scalar(select(Session).where(Session.token_digest == self.digest(token)))
        if record is None:
            return None
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= current_time:
            database.delete(record)
            database.flush()
            return None
        record.last_seen_at = current_time
        return record

    def csrf_is_valid(self, record: Session, csrf_token: str | None) -> bool:
        if not csrf_token:
            return False
        return hmac.compare_digest(record.csrf_digest, self.digest(csrf_token))

    def revoke(self, database: DatabaseSession, token: str) -> bool:
        result = database.execute(delete(Session).where(Session.token_digest == self.digest(token)))
        return bool(result.rowcount)

    def cleanup_expired(
        self,
        database: DatabaseSession,
        *,
        now: datetime | None = None,
    ) -> int:
        current_time = now or datetime.now(UTC)
        result = database.execute(delete(Session).where(Session.expires_at <= current_time))
        rowcount = result.rowcount
        return rowcount if rowcount is not None and rowcount >= 0 else 0
