"""HTTP-only MCP fixtures and safe SELECT observation; no host-side remote substitution."""

from __future__ import annotations

import uuid
from typing import Any

from .scenarios import AGENT, MISSING, SKILL, Scenario


class McpScenario(Scenario):
    def server(
        self,
        *,
        account: str = "teacher.alpha",
        connected: bool = False,
        base_url: str = "http://mcp-demo:8090",
    ) -> dict[str, Any]:
        server: dict[str, Any] = self.call(
            "POST",
            "/api/mcp/servers",
            account=account,
            body={
                "name": self.context.fixtures.name("mcp-" + uuid.uuid4().hex[:8]),
                "base_url": base_url,
            },
            status=201,
        )
        self.verify_server(server, account)
        if connected:
            server = self.call("POST", f"/api/mcp/servers/{server['id']}/connect", account=account)
            self.verify_server(server, account)
        return server

    def verify_server(self, server: dict[str, Any], account: str = "teacher.alpha") -> None:
        rows = self.context.database.rows(
            "SELECT id, class_id, name, base_url, state, connection_generation, safe_error_code "
            "FROM mcp_servers WHERE id = %s",
            (server["id"],),
        )
        self.checks.require(len(rows) == 1, "database.rows")
        row = rows[0]
        self.checks.require(
            str(row["class_id"]) == self.identity(account)["class_id"], "database.scope"
        )
        self.checks.require(
            all(
                row[key] == server[key]
                for key in ("name", "base_url", "state", "connection_generation", "safe_error_code")
            ),
            "mcp.registration",
        )
        self.checks.require(
            set(server)
            == {
                "id",
                "name",
                "base_url",
                "state",
                "connection_generation",
                "safe_error_code",
                "tool_count",
                "created_at",
                "updated_at",
            },
            "mcp.safe_fields",
        )

    def server_access(self, method: str, path: str, identifier: str) -> None:
        self.call(method, path, account=None, status=401)
        self.call(method, path, account="student.alpha", status=403)
        self.hidden(method, path, path.replace(identifier, MISSING), accounts=("teacher.beta",))

    def discovery(self, server: dict[str, Any]) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = self.call("GET", f"/api/mcp/servers/{server['id']}/tools")
        expected: set[str] = (
            {"formula_hint", "unit_convert"} if server["state"] == "connected" else set()
        )
        self.checks.require({tool["name"] for tool in tools} == expected, "mcp.discovery")
        self.checks.require(
            all(
                tool["supported"] and tool["tool_ref"] == f"{tool['name']}@{server['name']}"
                for tool in tools
            ),
            "mcp.discovery",
        )
        cached = self.context.database.rows(
            "SELECT name, generation FROM mcp_discovered_tools WHERE server_id = %s",
            (server["id"],),
        )
        self.checks.require(
            {row["name"] for row in cached} == expected
            and all(row["generation"] == server["connection_generation"] for row in cached),
            "database.rows",
        )
        return tools

    def bound_conversation(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        server = self.server(connected=True)
        reference = f"formula_hint@{server['name']}"
        skill: dict[str, Any] = self.call(
            "POST",
            "/api/skills",
            body={**SKILL, "tools": ["knowledge_search", reference]},
            status=201,
        )
        self.checks.require(skill["tools"] == ["knowledge_search", reference], "database.bindings")
        revisions = self.context.database.rows(
            "SELECT tools FROM skill_revisions WHERE id = %s",
            (skill["current_revision_id"],),
        )
        self.checks.require(
            len(revisions) == 1
            and revisions[0]["tools"]
            == [
                "knowledge_search",
                {
                    "server_id": server["id"],
                    "tool_name": "formula_hint",
                    "reference": reference,
                },
            ],
            "database.bindings",
        )
        agent = self.call(
            "POST", "/api/agents", body={**AGENT, "skill_ids": [skill["id"]]}, status=201
        )
        self.call("POST", f"/api/agents/{agent['id']}/publish")
        conversation: dict[str, Any] = self.call(
            "POST",
            "/api/conversations",
            account="student.alpha",
            body={"agent_id": agent["id"]},
            status=201,
        )
        return server, skill, conversation

    def verify_tool_turn(
        self, events: list[dict[str, Any]], server: dict[str, Any], status: str, code: str
    ) -> None:
        terminal = events[-1]["data"]
        expected = [{"tool_ref": f"formula_hint@{server['name']}", "status": status, "code": code}]
        self.checks.require(terminal["meta"]["tool_calls"] == expected, "stream.tool_calls")
        messages = self.context.database.rows(
            "SELECT tool_calls FROM conversation_messages WHERE id = %s",
            (terminal["assistant_message_id"],),
        )
        audits = self.context.database.rows(
            "SELECT server_id, tool_ref, status, code, execution_state, class_id, user_id "
            "FROM mcp_tool_calls WHERE assistant_message_id = %s",
            (terminal["assistant_message_id"],),
        )
        self.checks.require(
            len(messages) == 1 and messages[0]["tool_calls"] == expected, "database.messages"
        )
        self.checks.require(
            len(audits) == 1
            and {key: audits[0][key] for key in ("tool_ref", "status", "code")} == expected[0]
            and audits[0]["execution_state"] == "finalized"
            and str(audits[0]["server_id"]) == server["id"],
            "mcp.audit",
        )
        self.checks.require(
            str(audits[0]["class_id"]) == self.identity("student.alpha")["class_id"]
            and str(audits[0]["user_id"]) == self.identity("student.alpha")["user_id"],
            "database.scope",
        )
        history = self.call(
            "GET", f"/api/conversations/{terminal['conversation_id']}", account="student.alpha"
        )
        assistant = next(
            row for row in history["messages"] if row["id"] == terminal["assistant_message_id"]
        )
        self.checks.require(assistant["tool_calls"] == expected, "stream.tool_calls")
