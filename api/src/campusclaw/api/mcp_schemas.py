"""Safe MCP HTTP contracts; never credentials or remote response envelopes."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from campusclaw.api.schemas import StrictModel


class McpRegisterRequest(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$", examples=["campus-tools"])
    base_url: str = Field(
        min_length=1,
        max_length=2048,
        examples=["http://mcp-demo:8090"],
        description="Deployment-approved origin only; no userinfo, query, fragment or /mcp path.",
    )


class McpServerResponse(StrictModel):
    id: uuid.UUID
    name: str
    base_url: str
    state: Literal["disconnected", "connecting", "connected", "error"]
    connection_generation: int
    safe_error_code: str | None
    tool_count: int = 0
    created_at: datetime
    updated_at: datetime


class McpServerPage(StrictModel):
    items: list[McpServerResponse]
    next_cursor: str | None = None


class McpToolResponse(StrictModel):
    name: str
    tool_ref: str
    description: str
    input_schema: dict[str, Any]
    supported: bool
    code: Literal["tool_schema_unsupported"] | None = None


class McpAuditResponse(StrictModel):
    id: uuid.UUID
    server_id: uuid.UUID | None
    tool_ref: str
    status: Literal["ok", "denied", "error"]
    code: str
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    assistant_message_id: uuid.UUID
    created_at: datetime
    completed_at: datetime


class McpAuditPage(StrictModel):
    items: list[McpAuditResponse]
    next_cursor: str | None = None
