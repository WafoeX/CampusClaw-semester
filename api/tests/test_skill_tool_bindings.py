"""Task 4 transactional bindings/revision checks; controlled PostgreSQL discovery fixtures."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from threading import Event
from typing import Any

import pytest
from sqlalchemy import func, select

from campusclaw.application.mcp_servers import McpServerService
from campusclaw.application.skills import SkillService
from campusclaw.domain.models import (
    Agent,
    AgentRevision,
    AgentSkillBinding,
    ConversationMessage,
    McpDiscoveredTool,
    McpServer,
    Skill,
    SkillRevision,
)
from tests import test_agent_conversation_postgres as fixtures
from tests.test_agent_conversation_postgres import Context

api34 = fixtures.api34
pytestmark = pytest.mark.integration
BASE: dict[str, Any] = {
    "name": "Guidance",
    "skill_type": "solution_guidance",
    "instructions": "Give hints.",
}


def seed_server(
    c: Context, *, actor: str = "teacher.alpha", name: str = "campus-tools"
) -> uuid.UUID:
    principal = c.principals[actor]
    with c.database.transaction() as session:
        server = McpServer(
            class_id=principal.class_id,
            created_by=principal.user_id,
            name=name,
            base_url="http://mcp-demo:8090",
            state="connected",
            connection_generation=1,
        )
        session.add(server)
        session.flush()
        for tool_name in ["formula_hint", "unit_convert", *(f"tool{i}" for i in range(9))]:
            session.add(
                McpDiscoveredTool(
                    server_id=server.id,
                    class_id=principal.class_id,
                    generation=1,
                    name=tool_name,
                    description="Controlled metadata",
                    input_schema={
                        "type": "object",
                        "required": ["question"],
                        "properties": {"question": {"type": "string"}},
                        "additionalProperties": False,
                    },
                )
            )
        return server.id


def skill(c: Context, references: list[str]) -> dict[str, Any]:
    response = c.client.post(
        "/api/skills", headers=c.headers["teacher.alpha"], json=BASE | {"tools": references}
    )
    assert response.status_code == 201
    return dict(response.json())


def agent(c: Context, skill_ids: list[str], *, publish: bool = True) -> dict[str, Any]:
    response = c.client.post(
        "/api/agents",
        headers=c.headers["teacher.alpha"],
        json={
            "name": "Tutor",
            "description": "Guide",
            "system_prompt": "Evidence only.",
            "skill_ids": skill_ids,
        },
    )
    assert response.status_code == 201
    if publish:
        response = c.client.post(
            f"/api/agents/{response.json()['id']}/publish", headers=c.headers["teacher.alpha"]
        )
        assert response.status_code == 200
    return dict(response.json())


def counts(c: Context) -> dict[str, int]:
    with c.database.transaction() as session:
        return {
            model.__tablename__: int(session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (Skill, SkillRevision, Agent, AgentRevision, AgentSkillBinding)
        }


@pytest.mark.parametrize(
    "condition,code",
    [
        ("disconnected", "server_disconnected"),
        ("stale_cache", "tool_not_discovered"),
        ("undiscovered", "tool_not_discovered"),
        ("unsupported", "tool_schema_unsupported"),
    ],
)
def test_unavailable_binding_returns_409_and_rolls_back(
    api34: Context,
    condition: str,
    code: str,
) -> None:
    c = api34
    server_id = seed_server(c)
    original = skill(c, ["formula_hint@campus-tools"])
    published = agent(c, [original["id"]])
    with c.database.transaction() as session:
        server = session.get(McpServer, server_id)
        assert server is not None
        if condition == "disconnected":
            server.state = "disconnected"
        elif condition == "stale_cache":
            server.connection_generation += 1
        else:
            discovered = session.scalar(
                select(McpDiscoveredTool).where(
                    McpDiscoveredTool.server_id == server_id,
                    McpDiscoveredTool.name == "formula_hint",
                )
            )
            assert discovered is not None
            if condition == "undiscovered":
                session.delete(discovered)
            else:
                discovered.input_schema = {"type": "number"}
    before = counts(c)
    for method in ("post", "patch"):
        path = "/api/skills" if method == "post" else f"/api/skills/{original['id']}"
        response = c.client.request(
            method,
            path,
            headers=c.headers["teacher.alpha"],
            json=BASE | {"tools": ["formula_hint@campus-tools"]},
        )
        assert response.status_code == 409 and response.json()["detail"]["code"] == code
        assert counts(c) == before
    omitted = c.client.patch(
        f"/api/skills/{original['id']}", headers=c.headers["teacher.alpha"], json=BASE
    )
    assert omitted.status_code == 409
    unchanged = c.client.get(
        f"/api/agents/{published['id']}", headers=c.headers["teacher.alpha"]
    ).json()
    assert unchanged["state"] == "published"
    assert unchanged["current_revision_id"] == published["current_revision_id"]
    cleared = c.client.patch(
        f"/api/skills/{original['id']}",
        headers=c.headers["teacher.alpha"],
        json=BASE | {"tools": []},
    )
    assert cleared.status_code == 200 and cleared.json()["tools"] == []


def test_missing_and_cross_class_bindings_are_hidden_without_partial_writes(api34: Context) -> None:
    c = api34
    seed_server(c, actor="teacher.beta", name="beta-only")
    before = counts(c)
    for reference in ["formula_hint@beta-only", "formula_hint@missing"]:
        response = c.client.post(
            "/api/skills", headers=c.headers["teacher.alpha"], json=BASE | {"tools": [reference]}
        )
        assert response.status_code == 404 and counts(c) == before


def test_retained_reference_never_rebinds_foreign_stable_id(api34: Context) -> None:
    c = api34
    own_id, foreign_id = seed_server(c), seed_server(c, actor="teacher.beta")
    original = skill(c, ["formula_hint@campus-tools"])
    revision_id = uuid.UUID(original["current_revision_id"])
    with c.database.transaction() as session:
        revision = session.get(SkillRevision, revision_id)
        assert revision is not None and revision.tools[0]["server_id"] == str(own_id)
        # Controlled invalid old snapshot: a same-named own-class server must
        # never make a stored foreign identity authorized or silently rebind it.
        revision.tools = [
            {
                "server_id": str(foreign_id),
                "tool_name": "formula_hint",
                "reference": "formula_hint@campus-tools",
            }
        ]
    before = counts(c)
    for payload in [BASE, BASE | {"tools": ["formula_hint@campus-tools"]}]:
        response = c.client.patch(
            f"/api/skills/{original['id']}", headers=c.headers["teacher.alpha"], json=payload
        )
        assert response.status_code == 404 and counts(c) == before


def test_binding_validation_lock_is_held_until_skill_commit(api34: Context) -> None:
    c = api34
    server_id = seed_server(c)
    principal = c.principals["teacher.alpha"]
    entered = Event()

    def disconnect() -> None:
        with c.database.session_factory() as session:
            entered.set()
            McpServerService(c.settings).disconnect(session, principal, server_id)

    with c.database.transaction() as saving:
        created = SkillService(c.settings).create(
            saving, principal, **BASE, tools=["formula_hint@campus-tools"]
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(disconnect)
            try:
                assert entered.wait(2)
                with pytest.raises(FutureTimeout):
                    future.result(timeout=0.1)
            finally:
                saving.commit()  # Release before executor joins, including on assertion failure.
            future.result(timeout=5)
        revision_id = created.current_revision_id
    with c.database.transaction() as session:
        server = session.get(McpServer, server_id)
        revision = session.get(SkillRevision, revision_id)
        assert server is not None and server.state == "disconnected"
        assert revision is not None and revision.tools[0]["server_id"] == str(server_id)


def test_revision_propagation_republication_and_old_history_are_immutable(api34: Context) -> None:
    c = api34
    seed_server(c)
    original = skill(c, ["formula_hint@campus-tools"])
    published = agent(c, [original["id"]])
    conversation = c.conversation(published["id"])
    messages = f"/api/conversations/{conversation['id']}/messages"
    first = c.client.post(messages, headers=c.headers["student.alpha"], json={"content": "无资料"})
    assert first.status_code == 200 and "message.completed" in first.text
    updated = c.client.patch(
        f"/api/skills/{original['id']}",
        headers=c.headers["teacher.alpha"],
        json=BASE | {"tools": ["unit_convert@campus-tools"]},
    )
    assert updated.status_code == 200
    current = c.client.get(
        f"/api/agents/{published['id']}", headers=c.headers["teacher.alpha"]
    ).json()
    assert current["state"] == "draft" and current["published_revision_id"] is None
    assert current["current_revision_id"] != published["current_revision_id"]
    blocked = c.client.post(
        messages, headers=c.headers["student.alpha"], json={"content": "无资料"}
    )
    assert blocked.status_code == 409
    republished = c.client.post(
        f"/api/agents/{published['id']}/publish", headers=c.headers["teacher.alpha"]
    )
    assert republished.status_code == 200
    assert republished.json()["published_revision_id"] == current["current_revision_id"]
    second = c.client.post(messages, headers=c.headers["student.alpha"], json={"content": "无资料"})
    assert second.status_code == 200 and "message.completed" in second.text
    with c.database.transaction() as session:
        turns = list(
            session.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == uuid.UUID(conversation["id"]),
                    ConversationMessage.role == "assistant",
                )
                .order_by(ConversationMessage.ordinal)
            )
        )
        assert [str(t.applied_agent_revision_id) for t in turns] == [
            published["current_revision_id"],
            current["current_revision_id"],
        ]
        old = session.get(SkillRevision, uuid.UUID(original["current_revision_id"]))
        new = session.get(SkillRevision, uuid.UUID(updated.json()["current_revision_id"]))
        assert old is not None and old.tools[0]["tool_name"] == "formula_hint"
        assert new is not None and new.tools[0]["tool_name"] == "unit_convert"
        bound = session.scalar(
            select(AgentSkillBinding).where(
                AgentSkillBinding.agent_revision_id == uuid.UUID(current["current_revision_id"])
            )
        )
        assert bound is not None and bound.skill_revision_id == new.id
    for actor in ["teacher.peer", "teacher.beta"]:
        assert (
            c.client.patch(
                f"/api/skills/{original['id']}", headers=c.headers[actor], json=BASE | {"tools": []}
            ).status_code
            == 404
        )
    assert (
        c.client.patch(
            f"/api/skills/{original['id']}",
            headers=c.headers["student.alpha"],
            json=BASE | {"tools": []},
        ).status_code
        == 403
    )


def test_agent_create_update_and_publish_enforce_merged_limit(api34: Context) -> None:
    c = api34
    seed_server(c)
    first = skill(c, [f"tool{i}@campus-tools" for i in range(5)])
    other = skill(c, [f"tool{i}@campus-tools" for i in range(5, 9)])
    headers = c.headers["teacher.alpha"]
    payload = {
        "name": "Tutor",
        "system_prompt": "Evidence only.",
        "skill_ids": [first["id"], other["id"]],
    }
    before = counts(c)
    response = c.client.post("/api/agents", headers=headers, json=payload)
    assert response.status_code == 400 and counts(c) == before
    valid = agent(c, [first["id"]])
    before = counts(c)
    response = c.client.patch(f"/api/agents/{valid['id']}", headers=headers, json=payload)
    assert response.status_code == 400 and counts(c) == before
    current = c.client.get(f"/api/agents/{valid['id']}", headers=headers).json()
    assert (
        current["state"] == "published"
        and current["current_revision_id"] == valid["current_revision_id"]
    )
    with c.database.transaction() as session:
        # A controlled over-limit historical configuration must also fail publication.
        session.add(
            AgentSkillBinding(
                agent_revision_id=uuid.UUID(valid["current_revision_id"]),
                skill_revision_id=uuid.UUID(other["current_revision_id"]),
                class_id=c.principals["teacher.alpha"].class_id,
                creator_id=c.principals["teacher.alpha"].user_id,
            )
        )
    response = c.client.post(f"/api/agents/{valid['id']}/publish", headers=headers)
    assert response.status_code == 409


def test_duplicate_refs_across_skills_count_once(api34: Context) -> None:
    c = api34
    seed_server(c)
    eight = [f"tool{i}@campus-tools" for i in range(8)]
    first, second = skill(c, eight), skill(c, eight)
    result = agent(c, [first["id"], second["id"]])
    assert result["state"] == "published"


def test_over_limit_skill_propagation_rolls_back_every_revision(api34: Context) -> None:
    c = api34
    seed_server(c)
    first = skill(c, [f"tool{i}@campus-tools" for i in range(4)])
    other = skill(c, [f"tool{i}@campus-tools" for i in range(4, 8)])
    standalone, combined = agent(c, [first["id"]]), agent(c, [first["id"], other["id"]])
    before = counts(c)
    response = c.client.patch(
        f"/api/skills/{first['id']}",
        headers=c.headers["teacher.alpha"],
        json=BASE | {"tools": [*(f"tool{i}@campus-tools" for i in range(4)), "tool8@campus-tools"]},
    )
    assert (
        response.status_code == 409 and response.json()["detail"]["code"] == "call_limit_exceeded"
    )
    assert counts(c) == before
    for original in [standalone, combined]:
        current = c.client.get(
            f"/api/agents/{original['id']}", headers=c.headers["teacher.alpha"]
        ).json()
        assert current["state"] == "published"
        assert current["current_revision_id"] == original["current_revision_id"]
        assert current["published_revision_id"] == original["published_revision_id"]
    current_skill = c.client.get(
        f"/api/skills/{first['id']}", headers=c.headers["teacher.alpha"]
    ).json()
    assert current_skill["current_revision_id"] == first["current_revision_id"]
