"""Typed SSE envelopes shared by serialization and OpenAPI, never provider passthrough."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from campusclaw.api.schemas import CitationSource, StrictModel, ToolCallMeta


class EventEnvelope(StrictModel):
    sequence: int = Field(ge=1)
    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID


class MessageStarted(EventEnvelope):
    configuration_revision_id: uuid.UUID
    configuration_updated: bool


class AnswerDelta(EventEnvelope):
    delta: str = Field(min_length=1, max_length=512)


class CitationEvent(EventEnvelope):
    source: CitationSource


class MessageCompleted(EventEnvelope):
    status: Literal["answered", "insufficient_evidence"]
    answer_length: int = Field(ge=1, le=20_000)
    answer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    requested_mode: Literal["hybrid"] = "hybrid"
    retrieval_mode: Literal["keyword", "vector", "hybrid", "keyword_only"]
    configuration_revision_id: uuid.UUID
    configuration_updated: bool
    completed_at: datetime
    meta: ToolCallMeta = Field(default_factory=ToolCallMeta)


class MessageError(EventEnvelope):
    code: Literal[
        "generation_failed",
        "generation_invalid",
        "answer_generation_unavailable",
        "generation_timeout",
        "source_unavailable",
    ]
    retryable: bool
    meta: ToolCallMeta = Field(default_factory=ToolCallMeta)


EVENT_MODELS: dict[str, type[EventEnvelope]] = {
    "message.started": MessageStarted,
    "answer.delta": AnswerDelta,
    "citation": CitationEvent,
    "message.completed": MessageCompleted,
    "message.error": MessageError,
}


def serialize_event(name: str, payload: EventEnvelope) -> bytes:
    if type(payload) is not EVENT_MODELS.get(name):
        raise ValueError("invalid event payload")
    return f"event: {name}\ndata: {payload.model_dump_json()}\n\n".encode()
