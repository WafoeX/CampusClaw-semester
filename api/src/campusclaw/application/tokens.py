"""JWT access-token issue and validation using the standard HS256 construction."""

import base64
import calendar
import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

ISSUER = "campusclaw-api"
AUDIENCE = "campusclaw-web"
ALGORITHM = "HS256"
_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class IssuedAccessToken:
    token: str
    expires_at: datetime


def _json_segment(value: dict[str, str | int]) -> str:
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _load_segment(segment: str) -> dict[str, Any] | None:
    if not _SEGMENT_PATTERN.fullmatch(segment):
        return None
    try:
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JWT claim")
        value[key] = item
    return value


class TokenService:
    """Issue and validate bounded signed access tokens without persistent token state."""

    def __init__(self, signing_key: str, lifetime_seconds: int) -> None:
        if len(signing_key.encode("utf-8")) < 32:
            raise ValueError("JWT signing key must contain at least 32 bytes")
        if lifetime_seconds <= 0:
            raise ValueError("access-token lifetime must be positive")
        self._signing_key = signing_key.encode("utf-8")
        self._lifetime = timedelta(seconds=lifetime_seconds)

    def issue(self, user_id: uuid.UUID, *, now: datetime | None = None) -> IssuedAccessToken:
        issued_at = now or datetime.now(UTC)
        expires_at = issued_at + self._lifetime
        header = _json_segment({"alg": ALGORITHM, "typ": "JWT"})
        payload = _json_segment(
            {
                "sub": str(user_id),
                "iat": calendar.timegm(issued_at.utctimetuple()),
                "exp": calendar.timegm(expires_at.utctimetuple()),
                "iss": ISSUER,
                "aud": AUDIENCE,
            }
        )
        signing_input = f"{header}.{payload}".encode("ascii")
        signature = hmac.new(self._signing_key, signing_input, hashlib.sha256).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        return IssuedAccessToken(
            token=f"{header}.{payload}.{encoded_signature}", expires_at=expires_at
        )

    def subject(self, token: str, *, now: datetime | None = None) -> uuid.UUID | None:
        parts = token.split(".")
        if len(parts) != 3 or not all(_SEGMENT_PATTERN.fullmatch(part) for part in parts):
            return None
        header, payload, encoded_signature = parts
        expected_signature = (
            base64.urlsafe_b64encode(
                hmac.new(
                    self._signing_key,
                    f"{header}.{payload}".encode("ascii"),
                    hashlib.sha256,
                ).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        if not hmac.compare_digest(encoded_signature, expected_signature):
            return None
        header_data = _load_segment(header)
        payload_data = _load_segment(payload)
        if header_data != {"alg": ALGORITHM, "typ": "JWT"} or payload_data is None:
            return None
        try:
            subject = payload_data["sub"]
            issued_at = payload_data["iat"]
            expires_at = payload_data["exp"]
            if (
                payload_data["iss"] != ISSUER
                or payload_data["aud"] != AUDIENCE
                or not isinstance(subject, str)
                or isinstance(issued_at, bool)
                or isinstance(expires_at, bool)
                or not isinstance(issued_at, int)
                or not isinstance(expires_at, int)
            ):
                return None
            current_time = calendar.timegm((now or datetime.now(UTC)).utctimetuple())
            if issued_at > current_time or expires_at <= current_time:
                return None
            return uuid.UUID(subject)
        except (KeyError, TypeError, ValueError):
            return None
