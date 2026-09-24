# pyright: basic, reportMissingImports=false
from pathlib import Path

import pytest
from pydantic import ValidationError

from campusclaw.config import Settings

DATABASE_URL = "postgresql+psycopg://test:test@db/test"
BASE: dict[str, object] = {
    "APP_ENV": "test",
    "DATABASE_URL": DATABASE_URL,
    "SESSION_HMAC_KEY": "k" * 32,
    "SESSION_COOKIE_SECURE": False,
    "UPLOAD_ROOT": Path("/tmp/campusclaw-test"),
}


def test_missing_secret_is_rejected_without_value_leak() -> None:
    values = {key: value for key, value in BASE.items() if key != "SESSION_HMAC_KEY"}
    with pytest.raises(ValidationError) as caught:
        Settings(**values)  # type: ignore[arg-type]
    assert "SESSION_HMAC_KEY" in str(caught.value)
    assert DATABASE_URL not in str(caught.value)


def test_empty_secret_is_rejected_without_echo() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(**(BASE | {"SESSION_HMAC_KEY": ""}))  # type: ignore[arg-type]
    assert "SESSION_HMAC_KEY" in str(caught.value)
    assert "input_value" not in str(caught.value)


def test_enabled_seed_requires_every_password() -> None:
    settings = Settings(**(BASE | {"SEED_DEMO_DATA": True}))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="requires all") as caught:
        settings.require_seed_passwords()
    assert "PASSWORD" not in str(caught.value)


def test_seed_passwords_are_secret_values() -> None:
    passwords = {
        "DEMO_ALPHA_TEACHER_PASSWORD": "alpha-teacher-secret",
        "DEMO_ALPHA_STUDENT_PASSWORD": "alpha-student-secret",
        "DEMO_BETA_TEACHER_PASSWORD": "beta-teacher-secret",
        "DEMO_BETA_STUDENT_PASSWORD": "beta-student-secret",
    }
    settings = Settings(**(BASE | passwords))  # type: ignore[arg-type]
    assert all(value.get_secret_value() for value in settings.require_seed_passwords().values())
    assert "alpha-teacher-secret" not in repr(settings)
