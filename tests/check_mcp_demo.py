"""Explicitly authorized live-demo smoke; run via Compose stdin, never print credentials.

Protocol mode runs in api with its runtime MCP credential. Workflow mode runs in
an ephemeral seed container with configured demo account credentials. Both use
normal internal HTTP endpoints, not database writes or a provider substitute.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any

import httpx


class DemoCheck:
    def __init__(self) -> None:
        self.stage = "start"
        self.result: dict[str, Any] = {}
        self.client = httpx.Client(timeout=110, trust_env=False, follow_redirects=False)

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: Any = None,
        status: int = 200,
    ) -> Any:
        response = self.client.request(
            method,
            "http://api:8000" + path,
            json=body,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        assert response.status_code == status
        return response.json()

    def protocol(self) -> None:
        self.stage = "protocol_health"
        token = os.environ.get("MCP_AUTH_TOKEN", "")
        assert token.strip()
        assert self.client.get("http://mcp-demo:8090/health").status_code == 200
        self.result["mcp_health"] = True
        self.stage = "protocol_auth"
        endpoint = "http://mcp-demo:8090/mcp"
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": "demo-smoke",
            "method": "tools/list",
            "params": {},
        }
        assert self.client.post(endpoint, json=payload).status_code == 401
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.stage = "protocol_initialize"
        response = self.client.post(
            endpoint,
            headers=headers,
            json={
                **payload,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "authorized-demo-smoke", "version": "1"},
                },
            },
        )
        assert (
            response.status_code == 200
            and response.json()["result"]["protocolVersion"] == "2024-11-05"
        )
        assert (
            self.client.post(
                endpoint,
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            ).status_code
            == 202
        )
        self.stage = "protocol_list_call"
        response = self.client.post(endpoint, headers=headers, json=payload)
        assert response.status_code == 200
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
            "formula_hint",
            "unit_convert",
        }
        response = self.client.post(
            endpoint,
            headers=headers,
            json={
                **payload,
                "method": "tools/call",
                "params": {
                    "name": "unit_convert",
                    "arguments": {"question": "将 100 cm 转换为 m"},
                },
            },
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert not result.get("isError", False) and "1 m" in result["content"][0]["text"]
        self.result.update(
            unauthenticated_rejected=True, bearer_discovery=True, actual_unit_conversion=True
        )

    def turn(self, conversation: str, student: str) -> dict[str, Any]:
        response = self.client.post(
            f"http://api:8000/api/conversations/{conversation}/messages",
            headers={"Authorization": f"Bearer {student}"},
            json={"content": "欧姆定律的适用条件应如何检查？"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events: list[tuple[str, dict[str, Any]]] = []
        for frame in response.text.replace("\r\n", "\n").split("\n\n"):
            lines = [line for line in frame.splitlines() if line and not line.startswith(":")]
            if not lines:
                continue
            assert (
                len(lines) == 2 and lines[0].startswith("event: ") and lines[1].startswith("data: ")
            )
            events.append((lines[0][7:], json.loads(lines[1][6:])))
        assert events[0][0] == "message.started" and events[-1][0] == "message.completed"
        assert [data["sequence"] for _, data in events] == list(range(1, len(events) + 1))
        terminal = events[-1][1]
        assert terminal["status"] in {"answered", "insufficient_evidence"}
        if terminal["status"] == "insufficient_evidence":
            assert (
                "".join(data["delta"] for name, data in events if name == "answer.delta")
                == "根据本班资料无法回答该问题"
            )
            assert not any(name == "citation" for name, _ in events)
        return terminal

    def workflow(self) -> None:
        self.stage = "api_health"
        assert self.request("GET", "/health")["status"] == "ok"
        self.result["api_health"] = True
        self.stage = "demo_login"
        tokens: dict[str, str] = {}
        for role in ("teacher", "student"):
            password = os.environ[f"DEMO_ALPHA_{role.upper()}_PASSWORD"]
            assert password
            tokens[role] = self.request(
                "POST", "/api/auth/login", body={"account": role + ".alpha", "password": password}
            )["access_token"]
        teacher, student = tokens["teacher"], tokens["student"]
        self.stage = "register_connect_discover"
        server = self.request(
            "POST",
            "/api/mcp/servers",
            token=teacher,
            body={"name": "smoke-" + uuid.uuid4().hex, "base_url": "http://mcp-demo:8090"},
            status=201,
        )
        base = f"/api/mcp/servers/{server['id']}"
        connected = self.request("POST", base + "/connect", token=teacher)
        assert connected["state"] == "connected" and connected["tool_count"] == 2
        tools = self.request("GET", base + "/tools", token=teacher)
        assert {tool["name"] for tool in tools} == {"formula_hint", "unit_convert"}
        self.result["host_discovery"] = True
        self.stage = "bind_publish"
        reference = "formula_hint@" + server["name"]
        skill = self.request(
            "POST",
            "/api/skills",
            token=teacher,
            status=201,
            body={
                "name": "MCP deployment smoke",
                "skill_type": "solution_guidance",
                "instructions": "先核对条件，再提供有资料支持的引导。",
                "tools": ["knowledge_search", reference],
            },
        )
        agent = self.request(
            "POST",
            "/api/agents",
            token=teacher,
            status=201,
            body={
                "name": "MCP deployment smoke",
                "description": "Authorized deployment acceptance",
                "system_prompt": "基于本班资料给出步骤与追问。",
                "skill_ids": [skill["id"]],
            },
        )
        self.request("POST", f"/api/agents/{agent['id']}/publish", token=teacher)
        conversation = self.request(
            "POST", "/api/conversations", token=student, status=201, body={"agent_id": agent["id"]}
        )
        self.stage = "bound_question"
        first = self.turn(conversation["id"], student)
        expected = [{"tool_ref": reference, "status": "ok", "code": "ok"}]
        assert first["meta"]["tool_calls"] == expected
        self.result.update(bound_turn_tool_ok=True, answer_status=first["status"])
        self.stage = "history_audit"
        history = self.request("GET", f"/api/conversations/{conversation['id']}", token=student)
        saved = next(
            row for row in history["messages"] if row["id"] == first["assistant_message_id"]
        )
        assert saved["tool_calls"] == expected
        audits = self.request("GET", f"/api/mcp/audits?server_id={server['id']}", token=teacher)
        assert len(audits["items"]) == 1
        assert {key: audits["items"][0][key] for key in ("tool_ref", "status", "code")} == expected[
            0
        ]
        self.result["stream_history_audit_match"] = True
        self.stage = "disconnect_denial"
        assert self.request("POST", base + "/disconnect", token=teacher)["state"] == "disconnected"
        assert self.request("GET", base + "/tools", token=teacher) == []
        second = self.turn(conversation["id"], student)
        denied = [{"tool_ref": reference, "status": "denied", "code": "server_disconnected"}]
        assert second["meta"]["tool_calls"] == denied
        history = self.request("GET", f"/api/conversations/{conversation['id']}", token=student)
        assert (
            next(row for row in history["messages"] if row["id"] == first["assistant_message_id"])[
                "tool_calls"
            ]
            == expected
        )
        assert (
            next(row for row in history["messages"] if row["id"] == second["assistant_message_id"])[
                "tool_calls"
            ]
            == denied
        )
        audits = self.request("GET", f"/api/mcp/audits?server_id={server['id']}", token=teacher)
        assert sorted(row["status"] for row in audits["items"]) == ["denied", "ok"]
        self.result.update(
            disconnected_tools_empty=True, next_turn_denied=True, old_ok_preserved=True
        )
        self.stage = "unpublish_smoke_agent"
        assert (
            self.request("POST", f"/api/agents/{agent['id']}/unpublish", token=teacher)["state"]
            == "draft"
        )
        self.result["smoke_agent_unpublished"] = True


def main() -> int:
    check = DemoCheck()
    try:
        if "--protocol" in sys.argv:
            check.protocol()
        else:
            check.workflow()
        print(json.dumps({"passed": True, **check.result}))
        return 0
    except Exception:
        print(json.dumps({"passed": False, "failed_stage": check.stage, "details_redacted": True}))
        return 1
    finally:
        check.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
