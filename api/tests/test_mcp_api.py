"""Class-shared MCP API and real PostgreSQL generation race checks."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from campusclaw.application.mcp_client import DiscoveredTool, McpClient, McpFailure
from campusclaw.application.mcp_servers import ConnectionSuperseded, McpServerService
from campusclaw.domain.models import McpDiscoveredTool, McpServer
from tests import test_agent_conversation_postgres as fixtures
from tests.test_agent_conversation_postgres import Context

api34 = fixtures.api34
pytestmark = pytest.mark.integration
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string", "maxLength": 2000}},
    "required": ["question"],
    "additionalProperties": False,
}
DEMO = [
    DiscoveredTool(name, "Safe description", SCHEMA) for name in ["formula_hint", "unit_convert"]
]


def register(
    c: Context, name: str = "campus-tools", actor: str = "teacher.alpha"
) -> dict[str, Any]:
    response = c.client.post(
        "/api/mcp/servers",
        headers=c.headers[actor],
        json={"name": name, "base_url": "http://mcp-demo:8090"},
    )
    assert response.status_code == 201
    payload: dict[str, Any] = response.json()
    assert payload["state"] == "disconnected" and payload["tool_count"] == 0
    assert set(payload) == {
        "id",
        "name",
        "base_url",
        "state",
        "connection_generation",
        "safe_error_code",
        "tool_count",
        "created_at",
        "updated_at",
    }
    return payload


def test_registration_authorization_and_paging(api34: Context) -> None:
    c = api34
    server = register(c)
    register(c, actor="teacher.beta")  # Same immutable name in a different class is valid.
    assert (
        c.client.post(
            "/api/mcp/servers",
            headers=c.headers["teacher.alpha"],
            json={"name": "campus-tools", "base_url": "http://mcp-demo:8090"},
        ).status_code
        == 409
    )
    for invalid in [
        {"name": "bad@name", "base_url": "http://mcp-demo:8090"},
        {"name": "other", "base_url": "http://localhost:8090"},
        {"name": "other", "base_url": "http://user:secret@mcp-demo:8090"},
        {"name": "other", "base_url": "http://mcp-demo:8090", "class_id": server["id"]},
        {"name": "other", "base_url": "http://mcp-demo:8090", "token": "raw-secret"},
    ]:
        response = c.client.post(
            "/api/mcp/servers", headers=c.headers["teacher.alpha"], json=invalid
        )
        assert response.status_code == 400
        assert "raw-secret" not in response.text and "user:secret" not in response.text
    register(c, "second")
    first = c.client.get("/api/mcp/servers?limit=1", headers=c.headers["teacher.peer"]).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = c.client.get(
        "/api/mcp/servers",
        params={"limit": 1, "cursor": first["next_cursor"]},
        headers=c.headers["teacher.alpha"],
    ).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert (
        c.client.get("/api/mcp/servers?cursor=bad", headers=c.headers["teacher.alpha"]).status_code
        == 400
    )
    for path in ["/api/mcp/servers", "/api/mcp/audits", f"/api/mcp/servers/{server['id']}/tools"]:
        assert c.client.get(path).status_code == 401
        assert c.client.get(path, headers=c.headers["student.alpha"]).status_code == 403
    for operation in ["connect", "disconnect", "tools"]:
        method = c.client.get if operation == "tools" else c.client.post
        path = f"/api/mcp/servers/{server['id']}/{operation}"
        assert method(path, headers=c.headers["teacher.beta"]).status_code == 404
        assert method(path, headers=c.headers["student.alpha"]).status_code == 403
        assert method(path).status_code == 401
    assert (
        c.client.get(
            f"/api/mcp/audits?server_id={server['id']}", headers=c.headers["teacher.beta"]
        ).status_code
        == 404
    )
    assert (
        c.client.patch(
            f"/api/mcp/servers/{server['id']}",
            headers=c.headers["teacher.alpha"],
            json={"name": "renamed"},
        ).status_code
        == 404
    )


def test_connect_tools_disconnect_and_unsupported_schema(
    api34: Context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = api34

    async def discover(_self: McpClient, _url: str) -> list[DiscoveredTool]:
        return DEMO + [DiscoveredTool("other", "Other contract", {"type": "number"})]

    monkeypatch.setattr(McpClient, "discover", discover)
    server = register(c)
    root = f"/api/mcp/servers/{server['id']}"
    response = c.client.post(root + "/connect", headers=c.headers["teacher.peer"])
    assert response.status_code == 200 and response.json()["tool_count"] == 3
    tools = c.client.get(root + "/tools", headers=c.headers["teacher.alpha"]).json()
    assert [t["tool_ref"] for t in tools if t["supported"]] == [
        "formula_hint@campus-tools",
        "unit_convert@campus-tools",
    ]
    assert next(t for t in tools if t["name"] == "other")["code"] == "tool_schema_unsupported"
    for _ in range(2):
        response = c.client.post(root + "/disconnect", headers=c.headers["teacher.peer"])
        assert response.status_code == 200 and response.json()["state"] == "disconnected"
        assert c.client.get(root + "/tools", headers=c.headers["teacher.alpha"]).json() == []
    with c.database.transaction() as session:
        assert list(session.scalars(select(McpDiscoveredTool))) == []


@pytest.mark.parametrize(
    "code",
    [
        "remote_unauthorized",
        "tool_timeout",
        "protocol_error",
        "invalid_discovery",
    ],
)
def test_failed_reconnection_clears_cache_and_preserves_legacy_paths(
    api34: Context,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    c = api34

    async def success(_self: McpClient, _url: str) -> list[DiscoveredTool]:
        return DEMO

    monkeypatch.setattr(McpClient, "discover", success)
    server = register(c)
    root = f"/api/mcp/servers/{server['id']}"
    assert c.client.post(root + "/connect", headers=c.headers["teacher.alpha"]).status_code == 200

    async def fail(_self: McpClient, _url: str) -> list[DiscoveredTool]:
        raise McpFailure(code)

    monkeypatch.setattr(McpClient, "discover", fail)
    response = c.client.post(root + "/connect", headers=c.headers["teacher.alpha"])
    assert response.status_code == 503 and response.json()["detail"]["code"] == code
    assert c.client.get(root + "/tools", headers=c.headers["teacher.alpha"]).json() == []
    listed = c.client.get("/api/mcp/servers", headers=c.headers["teacher.alpha"]).json()["items"]
    assert listed[0]["state"] == "error" and listed[0]["safe_error_code"] == code
    assert (
        c.client.post(
            "/api/knowledge/query",
            headers=c.headers["student.alpha"],
            json={"question": "无资料", "mode": "keyword"},
        ).status_code
        == 200
    )
    conversation = c.conversation(c.agent()["id"])
    turn = c.client.post(
        f"/api/conversations/{conversation['id']}/messages",
        headers=c.headers["student.alpha"],
        json={"content": "无资料"},
    )
    assert turn.status_code == 200 and "message.completed" in turn.text


def test_missing_runtime_credential_has_safe_503(api34: Context) -> None:
    c = api34
    server = register(c)
    response = c.client.post(
        f"/api/mcp/servers/{server['id']}/connect", headers=c.headers["teacher.alpha"]
    )
    assert (
        response.status_code == 503
        and response.json()["detail"]["code"] == "credential_unavailable"
    )


@pytest.mark.parametrize("replacement", ["disconnect", "new_connect"])
def test_late_connect_cannot_publish_old_cache(api34: Context, replacement: str) -> None:
    c = api34
    registered = register(c)
    server_id = uuid.UUID(registered["id"])
    principal = c.principals["teacher.alpha"]

    async def scenario() -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        class SlowClient(McpClient):
            async def discover(self, base_url: str) -> list[DiscoveredTool]:
                entered.set()
                await release.wait()
                return [DiscoveredTool("stale", "Must never publish", SCHEMA)]

        class FastClient(McpClient):
            async def discover(self, base_url: str) -> list[DiscoveredTool]:
                return DEMO

        slow = McpServerService(c.settings, client=SlowClient(c.settings))
        fast = McpServerService(c.settings, client=FastClient(c.settings))
        with c.database.session_factory() as first, c.database.session_factory() as second:
            task = asyncio.create_task(slow.connect(first, principal, server_id))
            await entered.wait()
            assert not first.in_transaction()  # The network wait holds no DB transaction.
            if replacement == "disconnect":
                fast.disconnect(second, principal, server_id)
            else:
                await fast.connect(second, principal, server_id)
            release.set()
            with pytest.raises(ConnectionSuperseded):
                await task
        with c.database.transaction() as session:
            server = session.get(McpServer, server_id)
            assert server is not None
            assert server.connection_generation == 2
            expected = [] if replacement == "disconnect" else ["formula_hint", "unit_convert"]
            assert [
                t.name
                for t in fast.repository.list_tools(
                    session,
                    class_id=principal.class_id,
                    server_id=server_id,
                )
            ] == expected

    asyncio.run(scenario())
