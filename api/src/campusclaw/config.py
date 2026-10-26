# pyright: basic, reportMissingImports=false
"""Validated server-only configuration."""

import os
import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    DEMO = "demo"
    PRODUCTION = "production"
    TEST = "test"


SecretKey = Annotated[SecretStr, Field(min_length=32)]
SeedPassword = Annotated[SecretStr, Field(min_length=1)]


def normalize_mcp_origin(value: str) -> str:
    """Parse an origin, never echoing a potentially credential-bearing URL."""
    try:
        if not value or any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or "?" in value
            or "#" in value
            or "\\" in value
        ):
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port
        suffix = (
            "" if port is None or port == {"http": 80, "https": 443}[parsed.scheme] else f":{port}"
        )
        return f"{parsed.scheme}://{host}{suffix}"
    except (ValueError, UnicodeError):
        raise ValueError(
            "MCP Base URL must be an HTTP(S) origin without credentials or extras"
        ) from None


class Settings(BaseSettings):
    """All runtime values that must remain on the server."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        populate_by_name=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    APP_ENV: AppEnvironment
    DATABASE_URL: Annotated[str, Field(min_length=1)]
    JWT_SIGNING_KEY: SecretKey
    JWT_ACCESS_TOKEN_LIFETIME_SECONDS: Annotated[int, Field(ge=300, le=604800)] = 28800
    UPLOAD_ROOT: Path
    UPLOAD_MAX_BYTES: Annotated[int, Field(ge=1, le=1_073_741_824)] = 52_428_800
    SEED_DEMO_DATA: bool = False
    DEMO_ALPHA_TEACHER_PASSWORD: SeedPassword | None = None
    DEMO_ALPHA_STUDENT_PASSWORD: SeedPassword | None = None
    DEMO_BETA_TEACHER_PASSWORD: SeedPassword | None = None
    DEMO_BETA_STUDENT_PASSWORD: SeedPassword | None = None

    # Knowledge retrieval remains server-only.  Optional endpoints let the
    # ordinary material library run while providers are deliberately disabled.
    EMBEDDING_ENDPOINT: Annotated[
        str | None,
        Field(validation_alias=AliasChoices("EMBEDDING_ENDPOINT", "EMBEDDING_BASE_URL")),
    ] = None
    EMBEDDING_API_KEY: SecretStr | None = None
    EMBEDDING_DATA_BOUNDARY: Literal["private", "approved_external"] = "private"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: Annotated[
        int,
        Field(
            ge=1,
            le=8192,
            validation_alias=AliasChoices("EMBEDDING_DIMENSION", "EMBEDDING_DIM"),
        ),
    ] = 1536
    EMBEDDING_TIMEOUT_SECONDS: Annotated[float, Field(gt=0, le=120)] = 15.0
    EMBEDDING_BATCH_SIZE: Annotated[int, Field(ge=1, le=128)] = 32
    EMBEDDING_MAX_RETRIES: Annotated[int, Field(ge=0, le=5)] = 2

    GENERATION_ENDPOINT: str | None = None
    GENERATION_API_KEY: SecretStr | None = None
    GENERATION_DATA_BOUNDARY: Literal["private", "approved_external"] = "private"
    GENERATION_MODEL: str = "grounded-answer"
    GENERATION_TEMPERATURE: Annotated[float, Field(ge=0, le=0.3)] = 0.0
    GENERATION_TIMEOUT_SECONDS: Annotated[float, Field(gt=0, le=120)] = 30.0
    GENERATION_MAX_OUTPUT_TOKENS: Annotated[int, Field(ge=32, le=2048)] = 256
    GENERATION_EVIDENCE_CHAR_BUDGET: Annotated[int, Field(ge=256, le=100_000)] = 6_000
    GENERATION_STRUCTURED_OUTPUT: bool = True
    GENERATION_PROMPT_VERSION: str = "grounded-v1"
    GENERATION_MAX_RETRIES: Annotated[int, Field(ge=0, le=2)] = 1

    MCP_AUTH_TOKEN: SecretStr | None = Field(default=None, repr=False)
    MCP_APPROVED_SERVERS: dict[str, str] = Field(
        default_factory=lambda: {"http://mcp-demo:8090": "MCP_AUTH_TOKEN"}
    )

    @model_validator(mode="after")
    def validate_mcp_approved_servers(self) -> "Settings":
        approved: dict[str, str] = {}
        for origin, variable in self.MCP_APPROVED_SERVERS.items():
            normalized = normalize_mcp_origin(origin)
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", variable):
                raise ValueError("MCP credential mapping requires an environment variable name")
            if normalized in approved:
                raise ValueError("MCP approved origins must be unique after normalization")
            approved[normalized] = variable
        self.MCP_APPROVED_SERVERS = approved
        return self

    def approved_mcp_origin(self, value: str) -> str:
        origin = normalize_mcp_origin(value)
        if origin not in self.MCP_APPROVED_SERVERS:
            raise ValueError("MCP server is not deployment-approved")
        return origin

    def mcp_credential(self, value: str) -> SecretStr | None:
        """Resolve only a deployment-approved mapping; absence disables MCP, not API."""
        origin = self.approved_mcp_origin(value)
        variable = self.MCP_APPROVED_SERVERS[origin]
        token = (
            self.MCP_AUTH_TOKEN
            if variable == "MCP_AUTH_TOKEN"
            else SecretStr(os.environ.get(variable, ""))
        )
        return token if token is not None and token.get_secret_value().strip() else None

    QDRANT_URL: str = "http://qdrant:6333"
    QDRANT_API_KEY: SecretStr | None = None
    QDRANT_COLLECTION: str = "campusclaw-knowledge-v1"
    QDRANT_DISTANCE: Literal["Cosine", "Dot", "Euclid"] = "Cosine"
    QDRANT_TIMEOUT_SECONDS: Annotated[float, Field(gt=0, le=60)] = 5.0

    QUERY_MAX_LENGTH: Annotated[int, Field(ge=1, le=10_000)] = 2_000
    QUERY_DEFAULT_RESULT_LIMIT: Annotated[int, Field(ge=1, le=50)] = 6
    QUERY_MAX_RESULT_LIMIT: Annotated[int, Field(ge=1, le=100)] = 12
    QUERY_MAX_CANDIDATES: Annotated[int, Field(ge=1, le=500)] = 100
    QUERY_RRF_K: Annotated[int, Field(ge=1, le=10_000)] = 60
    EXTRACTION_MAX_BYTES: Annotated[int, Field(ge=1, le=1_073_741_824)] = 52_428_800
    EXTRACTION_MAX_CHARS: Annotated[int, Field(ge=1, le=2_000_000)] = 500_000
    EXTRACTION_CHUNK_CHARS: Annotated[int, Field(ge=128, le=20_000)] = 800
    EXTRACTION_CHUNK_OVERLAP: Annotated[int, Field(ge=0, le=1_000)] = 120
    EXTRACTION_MAX_CHUNKS: Annotated[int, Field(ge=1, le=20_000)] = 2_000
    WORKER_LEASE_SECONDS: Annotated[int, Field(ge=5, le=86_400)] = 300
    WORKER_MAX_ATTEMPTS: Annotated[int, Field(ge=1, le=10)] = 3
    QA_RATE_LIMIT_PER_MINUTE: Annotated[int, Field(ge=1, le=1_000)] = 30

    AGENT_NAME_MAX_CHARS: Annotated[int, Field(ge=1, le=120)] = 120
    AGENT_DESCRIPTION_MAX_CHARS: Annotated[int, Field(ge=0, le=1_000)] = 1_000
    AGENT_PROMPT_MAX_CHARS: Annotated[int, Field(ge=1, le=20_000)] = 12_000
    SKILL_NAME_MAX_CHARS: Annotated[int, Field(ge=1, le=120)] = 120
    SKILL_INSTRUCTIONS_MAX_CHARS: Annotated[int, Field(ge=1, le=20_000)] = 12_000
    CONVERSATION_MESSAGE_MAX_CHARS: Annotated[int, Field(ge=1, le=20_000)] = 8_000
    CONVERSATION_HISTORY_MAX_MESSAGES: Annotated[int, Field(ge=1, le=100)] = 20
    CONVERSATION_HISTORY_MAX_CHARS: Annotated[int, Field(ge=1, le=200_000)] = 24_000
    SSE_HEARTBEAT_SECONDS: Annotated[float, Field(gt=0, le=60)] = 15.0
    SSE_TASK_TIMEOUT_SECONDS: Annotated[float, Field(gt=0, le=300)] = 90.0
    CONVERSATION_RATE_LIMIT_PER_MINUTE: Annotated[int, Field(ge=1, le=1_000)] = 30

    @model_validator(mode="after")
    def validate_provider_boundaries(self) -> "Settings":
        for prefix, endpoint, boundary, key in (
            (
                "EMBEDDING",
                self.EMBEDDING_ENDPOINT,
                self.EMBEDDING_DATA_BOUNDARY,
                self.EMBEDDING_API_KEY,
            ),
            (
                "GENERATION",
                self.GENERATION_ENDPOINT,
                self.GENERATION_DATA_BOUNDARY,
                self.GENERATION_API_KEY,
            ),
        ):
            if endpoint is None or not endpoint.strip():
                continue
            normalized = endpoint.strip()
            if not normalized or not normalized.startswith(("http://", "https://")):
                raise ValueError(f"{prefix}_ENDPOINT must be an HTTP(S) URL")
            if boundary == "approved_external" and not normalized.startswith("https://"):
                raise ValueError(f"{prefix}_ENDPOINT requires HTTPS for approved external mode")
            if boundary == "approved_external" and key is None:
                raise ValueError(f"{prefix}_API_KEY is required for approved external mode")
            if key is not None and not key.get_secret_value().strip():
                raise ValueError(f"{prefix}_API_KEY must not be empty")
        if not self.QDRANT_URL.strip().startswith(("http://", "https://")):
            raise ValueError("QDRANT_URL must be an HTTP(S) URL")
        if not self.QDRANT_COLLECTION.strip():
            raise ValueError("QDRANT_COLLECTION must not be empty")
        if not self.EMBEDDING_MODEL.strip() or not self.GENERATION_MODEL.strip():
            raise ValueError("provider model names must not be empty")
        if not self.GENERATION_PROMPT_VERSION.strip():
            raise ValueError("GENERATION_PROMPT_VERSION must not be empty")
        if self.QUERY_DEFAULT_RESULT_LIMIT > self.QUERY_MAX_RESULT_LIMIT:
            raise ValueError("QUERY_DEFAULT_RESULT_LIMIT must not exceed QUERY_MAX_RESULT_LIMIT")
        if self.EXTRACTION_CHUNK_OVERLAP >= self.EXTRACTION_CHUNK_CHARS:
            raise ValueError("EXTRACTION_CHUNK_OVERLAP must be smaller than chunk size")
        if self.CONVERSATION_HISTORY_MAX_CHARS < self.CONVERSATION_MESSAGE_MAX_CHARS:
            raise ValueError("CONVERSATION_HISTORY_MAX_CHARS must cover one maximum-sized message")
        if self.SSE_HEARTBEAT_SECONDS >= self.SSE_TASK_TIMEOUT_SECONDS:
            raise ValueError("SSE_HEARTBEAT_SECONDS must be shorter than the task timeout")
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
