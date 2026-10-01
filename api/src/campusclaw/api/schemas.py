# pyright: basic, reportMissingImports=false
"""Public API request and response models."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class LoginRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    account: str = Field(min_length=1, max_length=120)
    password: SecretStr


class IdentityResponse(BaseModel):
    user_id: uuid.UUID
    account: str
    role: str
    class_id: uuid.UUID


class LoginResponse(IdentityResponse):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class QuestionRequest(BaseModel):
    """Single-turn, class-scoped question.  Client class values are forbidden."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    question: str = Field(min_length=1, max_length=2_000)
    result_limit: int | None = Field(default=None, ge=1, le=100)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"


class CitationSource(BaseModel):
    source_id: str = Field(pattern=r"^S[1-9][0-9]{0,2}$")
    material_id: uuid.UUID
    title: str
    original_filename: str
    excerpt: str = Field(min_length=1, max_length=4_000)
    page: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=200)
    action: str = Field(min_length=1, max_length=500)


class KnowledgeAnswerResponse(BaseModel):
    status: Literal[
        "answered",
        "insufficient_evidence",
        "vector_unavailable",
        "answer_generation_unavailable",
        "generation_invalid",
    ]
    answer: str | None = None
    citations: list[str] = Field(default_factory=list, max_length=100)
    sources: list[CitationSource] = Field(default_factory=list, max_length=100)
    requested_mode: Literal["keyword", "vector", "hybrid"]
    effective_mode: Literal["keyword", "vector", "hybrid", "keyword_only"]
    retryable: bool = False


class MaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str
    content_type: str
    byte_size: int
    sha256: str
    uploader_id: uuid.UUID
    created_at: datetime
    retrieval_status: Literal["pending", "processing", "searchable", "unsupported", "failed"] = (
        "pending"
    )
