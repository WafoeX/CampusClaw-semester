import base64
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from campusclaw.application.tokens import ALGORITHM, AUDIENCE, ISSUER, TokenService


def encoded_segment(value: Mapping[str, object]) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )


def forged_token(
    key: bytes, payload: Mapping[str, object], header: Mapping[str, object] | None = None
) -> str:
    import hashlib
    import hmac

    encoded_header = encoded_segment(header or {"alg": ALGORITHM, "typ": "JWT"})
    encoded_payload = encoded_segment(payload)
    signature = hmac.new(
        key, f"{encoded_header}.{encoded_payload}".encode(), hashlib.sha256
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def test_issue_and_validate_claims() -> None:
    service = TokenService("k" * 32, 3600)
    user_id = uuid.uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    issued = service.issue(user_id, now=now)
    assert issued.token.count(".") == 2
    assert service.subject(issued.token, now=now + timedelta(minutes=1)) == user_id
    payload = json.loads(base64.urlsafe_b64decode(issued.token.split(".")[1] + "=="))
    assert set(payload) == {"sub", "iat", "exp", "iss", "aud"}
    assert "role" not in payload and "class_id" not in payload


def test_rejects_expired_malformed_and_invalid_claims() -> None:
    key = b"k" * 32
    service = TokenService(key.decode(), 60)
    user_id = uuid.uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    expired = service.issue(user_id, now=now - timedelta(minutes=2)).token
    base = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=1)).timestamp()),
        "iss": ISSUER,
        "aud": AUDIENCE,
    }
    assert service.subject(expired, now=now) is None
    assert service.subject("not-a-jwt", now=now) is None
    assert service.subject(forged_token(key, base | {"iss": "wrong"}), now=now) is None
    assert service.subject(forged_token(key, base | {"aud": "wrong"}), now=now) is None
    assert (
        service.subject(
            forged_token(key, {key: value for key, value in base.items() if key != "exp"}), now=now
        )
        is None
    )
    assert service.subject(forged_token(key, base, {"alg": "none", "typ": "JWT"}), now=now) is None
    assert service.subject(forged_token(b"z" * 32, base), now=now) is None


def test_token_policy_rejects_weak_key_and_invalid_lifetime() -> None:
    try:
        TokenService("short", 60)
    except ValueError as error:
        assert "at least 32" in str(error)
    else:
        raise AssertionError("weak key accepted")
    try:
        TokenService("k" * 32, 0)
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("invalid lifetime accepted")
