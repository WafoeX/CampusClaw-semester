"""Controlled HTTP protocol and deadline checks, distinct from real-container E2E."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from campusclaw.application import mcp_client as module
from campusclaw.application.mcp_client import McpClient, McpFailure, validate_discovery
from campusclaw.config import Settings

ORIGIN = "http://mcp-demo:8090"
TOKEN = "synthetic-host-runtime-secret"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string", "maxLength": 2000}},
    "required": ["question"],
    "additionalProperties": False,
}
TOOL: dict[str, Any] = {"name": "formula_hint", "description": "fixed hint", "inputSchema": SCHEMA}


def reply(request: httpx.Request, result: object) -> httpx.Response:
    return httpx.Response(
        200, json={"jsonrpc": "2.0", "id": json.loads(request.content)["id"], "result": result}
    )


def test_discovery_handshake_and_server_only_credentials(settings: Settings) -> None:
    requests: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == ORIGIN + "/mcp"
        assert request.headers["authorization"] == "Bearer " + TOKEN
        payload: dict[str, Any] = json.loads(request.content)
        requests.append(payload)
        if payload["method"] == "initialize":
            assert payload["params"]["protocolVersion"] == "2024-11-05"
            return reply(
                request,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "test", "version": "1"},
                },
            )
        if payload["method"] == "notifications/initialized":
            assert "id" not in payload
            return httpx.Response(202)
        return reply(request, {"tools": [TOOL]})

    config = settings.model_copy(update={"MCP_AUTH_TOKEN": SecretStr(TOKEN)})
    client = McpClient(
        config, factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    tools = asyncio.run(client.discover(ORIGIN))
    assert tools[0].supported and tools[0].name == "formula_hint"
    assert [r["method"] for r in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]
    assert module.RPC_TIMEOUT == 3 and module.CONNECT_TIMEOUT == 8


@pytest.mark.parametrize(
    "fault,code",
    [
        ("unauthorized", "remote_unauthorized"),
        ("timeout", "tool_timeout"),
        ("network", "remote_unavailable"),
        ("redirect", "protocol_error"),
        ("wrong_id", "protocol_error"),
        ("rpc_error", "protocol_error"),
        ("oversize", "response_too_large"),
        ("malformed", "protocol_error"),
        ("secret_echo", "protocol_error"),
        ("bad_version", "protocol_error"),
    ],
)
def test_safe_connection_failures_without_retries(
    settings: Settings, fault: str, code: str
) -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if fault == "timeout":
            raise httpx.ReadTimeout(TOKEN)
        if fault == "network":
            raise httpx.ConnectError(TOKEN)
        if fault == "unauthorized":
            return httpx.Response(401, text=TOKEN)
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "http://unapproved/"})
        if fault == "wrong_id":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": "wrong", "result": {}})
        if fault == "rpc_error":
            return httpx.Response(200, json={"error": {"message": TOKEN}})
        if fault == "oversize":
            return httpx.Response(200, content=b" " * 65537)
        if fault == "malformed":
            return httpx.Response(
                200, headers={"Content-Type": "application/json"}, content=b"{NaN}"
            )
        result: dict[str, Any] = {
            "protocolVersion": "bad" if fault == "bad_version" else "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": TOKEN, "version": "1"},
        }
        return reply(request, result)

    client = McpClient(
        settings.model_copy(update={"MCP_AUTH_TOKEN": SecretStr(TOKEN)}),
        factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(McpFailure) as caught:
        asyncio.run(client.discover(ORIGIN))
    assert caught.value.code == code
    assert TOKEN not in str(caught.value)
    assert len(calls) == 1


def test_missing_credential_never_sends_http(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("HTTP dispatched without runtime credential")

    client = McpClient(
        settings.model_copy(update={"MCP_AUTH_TOKEN": None}),
        factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(McpFailure, match="运行时凭证"):
        asyncio.run(client.discover(ORIGIN))


INVALID_DISCOVERIES: list[dict[str, Any]] = [
    {},
    {"tools": "invalid"},
    {"tools": [TOOL] * 51},
    {"tools": [TOOL, TOOL]},
    {"tools": [{"name": "bad-name", "inputSchema": {}}]},
    {"tools": [{"name": "valid", "inputSchema": [], "description": "x"}]},
    {"tools": [{"name": "valid", "inputSchema": {}, "description": "x" * 1001}]},
    {"tools": [TOOL], "nextCursor": "unsupported-paging"},
    {"tools": [{"name": "valid", "inputSchema": {"required": "question"}}]},
    {"tools": [{"name": "valid", "inputSchema": {"type": 17}}]},
    {"tools": [{"name": "valid", "inputSchema": {"properties": {"question": 7}}}]},
]


@pytest.mark.parametrize("result", INVALID_DISCOVERIES)
def test_invalid_discovery_is_not_cached(result: dict[str, Any]) -> None:
    with pytest.raises(McpFailure) as caught:
        validate_discovery(result)
    assert caught.value.code == "invalid_discovery"


def test_valid_but_incompatible_tools_are_explicitly_unsupported() -> None:
    assert not validate_discovery(
        {
            "tools": [
                {
                    "name": "other",
                    "inputSchema": {
                        "type": "object",
                        "required": ["number"],
                        "properties": {"number": {"type": "number"}},
                    },
                }
            ]
        }
    )[0].supported


@pytest.mark.parametrize(
    "result,code",
    [
        ({"isError": True, "content": [{"type": "text", "text": "unsupported"}]}, "tool_error"),
        ({"content": []}, "invalid_tool_result"),
        ({"content": [{"type": "image", "data": "raw"}]}, "invalid_tool_result"),
        ({"content": [{"type": "text", "text": ""}]}, "invalid_tool_result"),
        ({"content": [{"type": "text", "text": "x" * 4001}]}, "invalid_tool_result"),
    ],
)
def test_tool_errors_do_not_return_text(
    settings: Settings, result: dict[str, Any], code: str
) -> None:
    client = McpClient(
        settings.model_copy(update={"MCP_AUTH_TOKEN": SecretStr(TOKEN)}),
        factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: reply(r, result))
        ),
    )
    with pytest.raises(McpFailure) as caught:
        asyncio.run(client.call(ORIGIN, "formula_hint", "question"))
    assert caught.value.code == code


def test_current_question_is_bounded_and_call_is_not_retried(settings: Settings) -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload: dict[str, Any] = json.loads(request.content)
        calls.append(payload)
        assert payload["params"]["arguments"] == {"question": "q" * 2000}
        return reply(request, {"content": [{"type": "text", "text": "safe auxiliary text"}]})

    client = McpClient(
        settings.model_copy(update={"MCP_AUTH_TOKEN": SecretStr(TOKEN)}),
        factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert asyncio.run(client.call(ORIGIN, "formula_hint", "q" * 4000)) == "safe auxiliary text"
    assert len(calls) == 1


def test_connect_total_deadline_and_rpc_deadline(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return reply(request, {})

    client = McpClient(
        settings.model_copy(update={"MCP_AUTH_TOKEN": SecretStr(TOKEN)}),
        factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(slow_handler)),
    )
    for rpc_timeout, connect_timeout in [(0.01, 8), (3, 0.01)]:
        monkeypatch.setattr(module, "RPC_TIMEOUT", rpc_timeout)
        monkeypatch.setattr(module, "CONNECT_TIMEOUT", connect_timeout)
        with pytest.raises(McpFailure) as caught:
            asyncio.run(client.discover(ORIGIN))
        assert caught.value.code == "tool_timeout"
