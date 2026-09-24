# pyright: basic, reportMissingImports=false
"""Validated server-only configuration."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    DEMO = "demo"
    PRODUCTION = "production"
    TEST = "test"


SecretKey = Annotated[SecretStr, Field(min_length=32)]
SeedPassword = Annotated[SecretStr, Field(min_length=1)]


class Settings(BaseSettings):
    """All runtime values that must remain on the server."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    APP_ENV: AppEnvironment
    DATABASE_URL: Annotated[str, Field(min_length=1)]
    SESSION_HMAC_KEY: SecretKey
    SESSION_COOKIE_NAME: Annotated[str, Field(min_length=1)] = "campusclaw_session"
    SESSION_COOKIE_SECURE: bool = True
    SESSION_LIFETIME_SECONDS: Annotated[int, Field(ge=300, le=604800)] = 28800
    UPLOAD_ROOT: Path
    UPLOAD_MAX_BYTES: Annotated[int, Field(ge=1, le=1_073_741_824)] = 52_428_800
    SEED_DEMO_DATA: bool = False
    DEMO_ALPHA_TEACHER_PASSWORD: SeedPassword | None = None
    DEMO_ALPHA_STUDENT_PASSWORD: SeedPassword | None = None
    DEMO_BETA_TEACHER_PASSWORD: SeedPassword | None = None
    DEMO_BETA_STUDENT_PASSWORD: SeedPassword | None = None

    @model_validator(mode="after")
    def validate_environment(self) -> "Settings":
        if self.APP_ENV == AppEnvironment.PRODUCTION and not self.SESSION_COOKIE_SECURE:
            raise ValueError("production requires secure session cookies")
        return self

    def require_seed_passwords(self) -> dict[str, SecretStr]:
        """Return all seed passwords, failing before any seed side effect."""
        fields = {
            "alpha_teacher": self.DEMO_ALPHA_TEACHER_PASSWORD,
            "alpha_student": self.DEMO_ALPHA_STUDENT_PASSWORD,
            "beta_teacher": self.DEMO_BETA_TEACHER_PASSWORD,
            "beta_student": self.DEMO_BETA_STUDENT_PASSWORD,
        }
        missing = [name for name, value in fields.items() if value is None]
        if missing:
            raise ValueError("enabled demo seed requires all sample-account passwords")
        return {name: value for name, value in fields.items() if value is not None}


@lru_cache
def get_settings() -> Settings:
    """Load and cache validated process settings."""
    return Settings()  # pyright: ignore[reportCallIssue]


__all__ = ["AppEnvironment", "Settings", "ValidationError", "get_settings"]
