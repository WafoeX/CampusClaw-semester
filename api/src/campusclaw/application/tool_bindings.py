"""Resolve tool references to stable class-scoped server identities in one transaction."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from campusclaw.application.mcp_client import compatible_question_schema, obj
from campusclaw.domain.models import McpDiscoveredTool, McpServer, SkillRevision
from campusclaw.domain.tool_references import validate_tool_references


class MissingToolBinding(LookupError):
    pass


class ToolBindingConflict(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("Tool binding is unavailable; reconnect or remove it")


def reference_list(stored: list[Any]) -> list[str]:
    return [entry if isinstance(entry, str) else str(entry["reference"]) for entry in stored]


def resolve_bindings(
    session: Session,
    class_id: uuid.UUID,
    references: list[str],
    *,
    previous: list[Any] | None = None,
) -> list[Any]:
    validate_tool_references(references)
    previous_servers: dict[str, str] = {}
    for value in previous or []:
        entry = obj(value)
        if entry is not None:
            reference, server_id = entry.get("reference"), entry.get("server_id")
            if isinstance(reference, str) and isinstance(server_id, str):
                previous_servers[reference] = server_id
    resolved: dict[str, Any] = {}
    # Sort by server, not tool: different skill lists must acquire shared server
    # locks in the same order, including when their tool names differ.
    for reference in sorted(references, key=lambda ref: ref.split("@")[-1]):
        if reference == "knowledge_search":
            resolved[reference] = reference
            continue
        name, server_name = reference.split("@")
        server = session.scalar(
            select(McpServer)
            .where(
                McpServer.class_id == class_id,
                McpServer.name == server_name,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if server is None:
            raise MissingToolBinding
        if reference in previous_servers and previous_servers[reference] != str(server.id):
            # A retained display name never silently rebinds to a different ID.
            raise MissingToolBinding
        if server.state != "connected":
            raise ToolBindingConflict("server_disconnected")
        tool = session.scalar(
            select(McpDiscoveredTool).where(
                McpDiscoveredTool.class_id == class_id,
                McpDiscoveredTool.server_id == server.id,
                McpDiscoveredTool.generation == server.connection_generation,
                McpDiscoveredTool.name == name,
            )
        )
        if tool is None:
            raise ToolBindingConflict("tool_not_discovered")
        if not compatible_question_schema(tool.input_schema):
            raise ToolBindingConflict("tool_schema_unsupported")
        resolved[reference] = {
            "server_id": str(server.id),
            "tool_name": name,
            "reference": reference,
        }
    return [resolved[reference] for reference in references]


def ensure_tool_union(revisions: list[SkillRevision]) -> None:
    references = {
        ref
        for revision in revisions
        for ref in reference_list(revision.tools)
        if ref != "knowledge_search"
    }
    if len(references) > 8:
        raise ToolBindingConflict("call_limit_exceeded")
