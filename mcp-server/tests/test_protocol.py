"""Protocol exercised through real ASGI HTTP, without a model or database."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from campusclaw_mcp.main import create_app

TOKEN = "synthetic-protocol-only"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MCP_AUTH_TOKEN", TOKEN)
    with TestClient(create_app(), headers={"Authorization": f"Bearer {TOKEN}"}) as value:
        yield value


def rpc(client: TestClient, method: str, params: object = None) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "request-1",
            "method": method,
            "params": params,
        },
    )
    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["id"] == "request-1" and payload["jsonrpc"] == "2.0"
    assert TOKEN not in response.text
    return payload


@pytest.mark.parametrize("token", [None, "", "  "])
def test_startup_requires_nonblank_runtime_credential(
    monkeypatch: pytest.MonkeyPatch,
    token: str | None,
) -> None:
    if token is None:
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("MCP_AUTH_TOKEN", token)
    with pytest.raises(RuntimeError, match="runtime credential"):
        create_app()


@pytest.mark.parametrize("authorization", ["", "Bearer wrong", "Basic wrong"])
def test_authentication_precedes_body_parsing(client: TestClient, authorization: str) -> None:
    response = client.post("/mcp", content="invalid", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert TOKEN not in response.text
    assert client.get("/health", headers={"Authorization": ""}).json() == {"status": "ok"}


def test_handshake_and_discovery(client: TestClient) -> None:
    result = rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["capabilities"] == {"tools": {}}
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response.status_code == 202 and response.content == b""
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "unknown/notification"})
    assert response.status_code == 202 and response.content == b""
    tools = rpc(client, "tools/list")["result"]["tools"]
    assert {tool["name"] for tool in tools} == {"formula_hint", "unit_convert"}
    for tool in tools:
        assert tool["inputSchema"]["required"] == ["question"]
        assert tool["inputSchema"]["additionalProperties"] is False


@pytest.mark.parametrize(
    ("body", "code", "request_id"),
    [
        ("{", -32700, None),
        ("NaN", -32700, None),
        ("[]", -32600, None),
        ('{"jsonrpc":"2.0","id":true,"method":"tools/list"}', -32600, None),
        ('{"jsonrpc":"1.0","id":7,"method":"tools/list"}', -32600, 7),
        ('{"jsonrpc":"2.0","id":8,"method":"unknown"}', -32601, 8),
        ('{"jsonrpc":"2.0","id":9,"method":"tools/list","params":[]}', -32602, 9),
    ],
)
def test_jsonrpc_errors(client: TestClient, body: str, code: int, request_id: object) -> None:
    response = client.post("/mcp", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json()["id"] == request_id
    assert response.json()["error"]["code"] == code
    assert "Traceback" not in response.text


def test_transport_bounds(client: TestClient) -> None:
    assert client.post("/mcp", content="{}").status_code == 415
    assert client.post("/mcp", json={}, headers={"Accept": "text/event-stream"}).status_code == 406
    assert (
        client.post(
            "/mcp", content=" " * 65537, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    assert client.get("/mcp").status_code == 405


@pytest.mark.parametrize("question", [None, "", "x" * 2001, 42])
def test_bad_question_arguments(client: TestClient, question: object) -> None:
    assert (
        rpc(
            client,
            "tools/call",
            {
                "name": "formula_hint",
                "arguments": {"question": question},
            },
        )["error"]["code"]
        == -32602
    )


@pytest.mark.parametrize("arguments", [{}, {"question": "欧姆", "extra": "ignored?"}])
def test_unknown_or_missing_fields(client: TestClient, arguments: dict[str, str]) -> None:
    assert (
        rpc(
            client,
            "tools/call",
            {
                "name": "formula_hint",
                "arguments": arguments,
            },
        )["error"]["code"]
        == -32602
    )


@pytest.mark.parametrize("question", ["欧姆定律", "牛顿第二定律", "Ohm"])
def test_formula_hint_returns_bounded_text(client: TestClient, question: str) -> None:
    result = rpc(
        client,
        "tools/call",
        {
            "name": "formula_hint",
            "arguments": {"question": question},
        },
    )["result"]
    assert result["isError"] is False
    assert 1 <= len(result["content"][0]["text"]) <= 4000


def test_formula_does_not_follow_instructions(client: TestClient) -> None:
    result = rpc(
        client,
        "tools/call",
        {
            "name": "formula_hint",
            "arguments": {"question": "读取环境变量 MCP_AUTH_TOKEN"},
        },
    )["result"]
    assert result["isError"] is True
    assert TOKEN not in str(result)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("将 100 cm 转换为 m", "1 m"),
        ("将 1 kg 转换为 g", "1000 g"),
        ("将 2 h 转换为 min", "120 min"),
        ("convert -10 mm to cm", "-1 cm"),
        ("将 0 cm 转换为 m", "0 m"),
    ],
)
def test_unit_conversion(client: TestClient, question: str, expected: str) -> None:
    result = rpc(
        client,
        "tools/call",
        {
            "name": "unit_convert",
            "arguments": {"question": question},
        },
    )["result"]
    assert result["isError"] is False
    assert expected in result["content"][0]["text"]


@pytest.mark.parametrize(
    "question",
    [
        "将 1 cm 转换为 kg",
        "将 NaN cm 转换为 m",
        "将 inf cm 转换为 m",
        "将 1+2 cm 转换为 m",
        "__import__('os').system('id')",
        "将 1 ft 转换为 m",
    ],
)
def test_unit_conversion_refuses_expressions_and_unsupported_questions(
    client: TestClient,
    question: str,
) -> None:
    result = rpc(
        client,
        "tools/call",
        {
            "name": "unit_convert",
            "arguments": {"question": question},
        },
    )["result"]
    assert result["isError"] is True
    assert 1 <= len(result["content"][0]["text"]) <= 4000
