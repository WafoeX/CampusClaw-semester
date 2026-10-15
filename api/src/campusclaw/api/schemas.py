# pyright: basic, reportMissingImports=false
"""Public API request and response models."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


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


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class DomainError(StrictModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=300)
    retryable: bool | None = None


class DomainErrorResponse(StrictModel):
    detail: DomainError


class SafeValidationDetail(StrictModel):
    code: Literal["invalid_request"] = "invalid_request"
    message: Literal["Invalid request"] = "Invalid request"


class SafeValidationErrorResponse(StrictModel):
    detail: SafeValidationDetail


class AgentCreateRequest(StrictModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    system_prompt: str = Field(min_length=1, max_length=20_000)
    skill_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    @field_validator("name", "system_prompt")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("skill_ids")
    @classmethod
    def unique_skills(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate skill identifiers")
        return value


class AgentUpdateRequest(AgentCreateRequest):
    pass


class SkillCreateRequest(StrictModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=120)
    skill_type: Literal["solution_guidance"]
    instructions: str = Field(min_length=1, max_length=20_000)

    @field_validator("name", "instructions")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class SkillUpdateRequest(SkillCreateRequest):
    pass


class AgentResponse(StrictModel):
    id: uuid.UUID
    state: Literal["draft", "published", "retired"]
    name: str
    description: str | None
    system_prompt: str
    skill_ids: list[uuid.UUID]
    current_revision_id: uuid.UUID | None
    published_revision_id: uuid.UUID | None


class AgentCatalogResponse(StrictModel):
    id: uuid.UUID
    name: str
    description: str | None


class SkillResponse(StrictModel):
    id: uuid.UUID
    state: Literal["active", "retired"]
    name: str
    skill_type: Literal["solution_guidance"]
    instructions: str
    current_revision_id: uuid.UUID | None


class ConversationCreateRequest(StrictModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    agent_id: uuid.UUID


class ConversationMessageRequest(StrictModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("invalid message text")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("invalid message text") from None
        return value


class ConversationMessageResponse(StrictModel):
    id: uuid.UUID
    ordinal: int
    role: Literal["user", "assistant"]
    state: Literal["processing", "completed", "failed"]
    content: str | None = None
    safe_error_code: str | None = None
    retrieval_mode: str | None = None
    applied_agent_revision_id: uuid.UUID | None = None
    configuration_updated: bool = False
    created_at: datetime
    completed_at: datetime | None = None
    citations: list[CitationSource] = Field(default_factory=list, max_length=100)


class ConversationResponse(StrictModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str = Field(max_length=120)
    student_id: uuid.UUID
    student_account: str = Field(max_length=120)
    creator_retains_audit_access: Literal[True] = True
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageResponse] = Field(default_factory=list, max_length=100)
    next_after_ordinal: int | None = None


class ConversationListResponse(StrictModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str = Field(max_length=120)
    student_id: uuid.UUID
    student_account: str = Field(max_length=120)
    creator_retains_audit_access: Literal[True] = True
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


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
