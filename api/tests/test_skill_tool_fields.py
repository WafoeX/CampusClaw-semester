"""Task 4.1 field semantics, using explicit isolated discovery rows, not E2E claims."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from campusclaw.domain.models import McpDiscoveredTool, McpServer, Skill, SkillRevision
from tests import test_agent_conversation_postgres as fixtures
from tests.test_agent_conversation_postgres import Context

api34 = fixtures.api34
pytestmark = pytest.mark.integration
BASE: dict[str, Any] = {
    "name": "Guidance",
    "skill_type": "solution_guidance",
    "instructions": "Give hints only.",
}


def seed_tools(c: Context) -> uuid.UUID:
    principal = c.principals["teacher.alpha"]
    with c.database.transaction() as session:
        server = McpServer(
            class_id=principal.class_id,
            created_by=principal.user_id,
            name="campus-tools",
            base_url="http://mcp-demo:8090",
            state="connected",
            connection_generation=1,
        )
        session.add(server)
        session.flush()
        for name in ["formula_hint", *(f"tool{i}" for i in range(7))]:
            session.add(
                McpDiscoveredTool(
                    server_id=server.id,
                    class_id=principal.class_id,
                    generation=1,
                    name=name,
                    description="Controlled fixture metadata",
                    input_schema={
                        "type": "object",
                        "required": ["question"],
                        "properties": {"question": {"type": "string"}},
                        "additionalProperties": False,
                    },
                )
            )
        return server.id


def test_legacy_create_defaults_and_legacy_update_preserves_bindings(api34: Context) -> None:
    c = api34
    headers = c.headers["teacher.alpha"]
    legacy = c.client.post("/api/skills", headers=headers, json=BASE)
    assert legacy.status_code == 201 and legacy.json()["tools"] == ["knowledge_search"]
    server_id = seed_tools(c)
    references = ["knowledge_search", "formula_hint@campus-tools"]
    created = c.client.post("/api/skills", headers=headers, json=BASE | {"tools": references})
    assert created.status_code == 201 and created.json()["tools"] == references
    identity = created.json()["id"]
    revision_id = uuid.UUID(created.json()["current_revision_id"])
    with c.database.transaction() as session:
        revision = session.get(SkillRevision, revision_id)
        assert revision is not None
        original = list(revision.tools)
        assert original == [
            "knowledge_search",
            {
                "server_id": str(server_id),
                "tool_name": "formula_hint",
                "reference": "formula_hint@campus-tools",
            },
        ]
    updated = c.client.patch(
        f"/api/skills/{identity}", headers=headers, json=BASE | {"name": "Renamed"}
    )
    assert updated.status_code == 200 and updated.json()["tools"] == references
    assert updated.json()["current_revision_id"] != str(revision_id)
    assert c.client.get(f"/api/skills/{identity}", headers=headers).json()["tools"] == references
    listed = c.client.get("/api/skills", headers=headers).json()
    assert next(s for s in listed if s["id"] == identity)["tools"] == references
    cleared = c.client.patch(f"/api/skills/{identity}", headers=headers, json=BASE | {"tools": []})
    assert cleared.status_code == 200 and cleared.json()["tools"] == []
    with c.database.transaction() as session:
        old = session.get(SkillRevision, revision_id)
        assert old is not None and old.tools == original
        latest = session.get(SkillRevision, uuid.UUID(cleared.json()["current_revision_id"]))
        assert latest is not None and latest.tools == []


INVALID_TOOLS: list[object] = [
    None,
    "formula_hint@campus-tools",
    ["knowledge_search", "knowledge_search"],
    ["bad-tool@campus-tools"],
    ["formula_hint@BadServer"],
    ["formula_hint@campus-tools/evil"],
    ["unregistered_builtin"],
    ["@campus-tools"],
    ["formula_hint@"],
    [f"tool{i}@campus-tools" for i in range(9)],
    [17],
]


@pytest.mark.parametrize("tools", INVALID_TOOLS)
def test_invalid_tools_rejected_without_persisting_partial_skill(
    api34: Context, tools: object
) -> None:
    c = api34
    response = c.client.post(
        "/api/skills", headers=c.headers["teacher.alpha"], json=BASE | {"tools": tools}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_request", "message": "Invalid request"}}
    with c.database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Skill)) == 0
        assert session.scalar(select(func.count()).select_from(SkillRevision)) == 0


def test_eight_tool_field_limit_and_empty_list_are_explicit(api34: Context) -> None:
    c = api34
    seed_tools(c)
    headers = c.headers["teacher.alpha"]
    eight = ["formula_hint@campus-tools", *(f"tool{i}@campus-tools" for i in range(7))]
    response = c.client.post("/api/skills", headers=headers, json=BASE | {"tools": eight})
    assert response.status_code == 201 and response.json()["tools"] == eight
    identity = response.json()["id"]
    too_many = c.client.patch(
        f"/api/skills/{identity}",
        headers=headers,
        json=BASE | {"tools": ["knowledge_search", *eight]},
    )
    assert too_many.status_code == 400
    unchanged = c.client.get(f"/api/skills/{identity}", headers=headers).json()
    assert unchanged["current_revision_id"] == response.json()["current_revision_id"]
    empty = c.client.post("/api/skills", headers=headers, json=BASE | {"tools": []})
    assert empty.status_code == 201 and empty.json()["tools"] == []
