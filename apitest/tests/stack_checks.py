"""Task-8 support acceptance only; run explicitly in the isolated runner.

These are not Task-9 operation scripts or a claim of complete API coverage.
"""

from __future__ import annotations

import socket
import unittest
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import psycopg

from ..clients import Context, parse_sse


class StackChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.context = Context.from_environment()
        self.addCleanup(self.context.__exit__)
        self.client = self.context.client
        self.database = self.context.database

    def test_migration_fixtures_indexing_and_least_privilege(self) -> None:
        self.assertEqual(len(self.database.rows("SELECT version_num FROM alembic_version")), 1)
        users = self.database.rows("SELECT account, class_id FROM users ORDER BY account")
        self.assertEqual(len(users), 6)
        self.assertEqual(len({row["class_id"] for row in users}), 2)
        self.assertEqual(
            self.database.rows(
                "SELECT count(*) AS n FROM knowledge_chunks WHERE text LIKE %s", ("%ALPHA_FERN%",)
            )[0]["n"],
            1,
        )
        self.assertEqual(
            self.database.rows(
                "SELECT count(*) AS n FROM knowledge_chunks WHERE text LIKE %s", ("%BETA_CRYSTAL%",)
            )[0]["n"],
            1,
        )
        role = self.database.rows(
            "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
        )[0]
        self.assertFalse(any(role.values()))
        permissions = self.database.rows(
            "SELECT has_table_privilege(current_user, 'agents', 'INSERT') AS writes, "
            "has_schema_privilege(current_user, 'public', 'CREATE') AS creates, "
            "has_column_privilege(current_user, 'users', 'password_hash', 'SELECT') AS hashes"
        )[0]
        self.assertFalse(any(permissions.values()))
        with self.assertRaises(ValueError):
            self.database.rows("UPDATE agents SET lifecycle = lifecycle")
        with self.assertRaises(psycopg.Error), self.database.connection.transaction():
            self.database.connection.execute("DELETE FROM agents WHERE false")
        self.assertEqual(self.database.rows("SELECT 1 AS n")[0]["n"], 1)

    def test_mcp_reader_has_only_safe_columns_and_no_writes(self) -> None:
        permissions = self.database.rows(
            "SELECT has_table_privilege(current_user, 'mcp_tool_calls', 'INSERT') AS inserts, "
            "has_table_privilege(current_user, 'mcp_servers', 'UPDATE') AS updates, "
            "has_column_privilege(current_user, 'mcp_discovered_tools', 'description', 'SELECT') "
            "AS raw_description, "
            "has_column_privilege(current_user, 'mcp_discovered_tools', 'input_schema', 'SELECT') "
            "AS raw_schema, "
            "has_column_privilege(current_user, 'users', 'password_hash', 'SELECT') AS password"
        )[0]
        self.assertFalse(any(permissions.values()))
        self.assertEqual(
            self.database.rows(
                "SELECT count(*) AS n FROM mcp_tool_calls WHERE execution_state = %s", ("pending",)
            )[0]["n"],
            0,
        )
        with self.assertRaises(psycopg.Error), self.database.connection.transaction():
            self.database.connection.execute("SELECT input_schema FROM mcp_discovered_tools")
        with self.assertRaises(psycopg.Error), self.database.connection.transaction():
            self.database.connection.execute("DELETE FROM mcp_tool_calls WHERE false")

    def test_gateway_login_json_and_deterministic_provider_flow(self) -> None:
        status, health = self.client.json("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIsInstance(health, dict)
        token = self.client.login("student.alpha", "apitest-account-only")
        status, identity = self.client.json("GET", "/api/auth/me", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(identity["account"], "student.alpha")
        status, answer = self.client.json(
            "POST",
            "/api/knowledge/query",
            token=token,
            body={
                "question": "ALPHA_FERN",
                "mode": "keyword",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(answer["status"], "answered")
        self.assertEqual(answer["sources"][0]["title"], "ALPHA_FERN")
        status, refusal = self.client.json(
            "POST",
            "/api/knowledge/query",
            token=token,
            body={
                "question": "BETA_CRYSTAL",
                "mode": "keyword",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(refusal["answer"], "根据本班资料无法回答该问题")
        self.assertEqual(refusal["sources"], [])

    def test_shared_sse_parser_against_gateway_and_database(self) -> None:
        teacher = self.client.login("teacher.alpha", "apitest-account-only")
        student = self.client.login("student.alpha", "apitest-account-only")

        def create(path: str, body: dict[str, Any]) -> dict[str, Any]:
            status, result = self.client.json("POST", path, token=teacher, body=body)
            self.assertIn(status, (200, 201))
            return cast(dict[str, Any], result)

        skill = create(
            "/api/skills",
            {
                "name": self.context.fixtures.name("skill"),
                "skill_type": "solution_guidance",
                "instructions": "提供观察提示和追问，不给出最终结论。",
            },
        )
        agent = create(
            "/api/agents",
            {
                "name": self.context.fixtures.name("agent"),
                "system_prompt": "引导学生逐步观察。",
                "skill_ids": [skill["id"]],
            },
        )
        create(f"/api/agents/{agent['id']}/publish", {})
        status, conversation = self.client.json(
            "POST", "/api/conversations", token=student, body={"agent_id": agent["id"]}
        )
        self.assertEqual(status, 201)
        response = self.client.request(
            "POST",
            f"/api/conversations/{conversation['id']}/messages",
            token=student,
            body={"content": "ALPHA_FERN 只要最终答案"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        events = parse_sse(response.content)
        self.assertEqual(events[-1]["event"], "message.completed")
        self.assertEqual(events[-1]["data"]["status"], "answered")
        answer = "".join(
            event["data"]["delta"] for event in events if event["event"] == "answer.delta"
        )
        rows = self.database.rows(
            "SELECT role, state, content FROM conversation_messages "
            "WHERE conversation_id = %s ORDER BY ordinal",
            (conversation["id"],),
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["content"], answer)
        self.assertEqual(rows[1]["state"], "completed")
        self.assertIn("？", answer)
        self.assertEqual(
            len(
                self.database.rows(
                    "SELECT id FROM message_citations WHERE message_id = %s",
                    (events[-1]["data"]["assistant_message_id"],),
                )
            ),
            1,
        )

    def test_actual_mcp_service_is_isolated_and_deterministic(self) -> None:
        with httpx.Client(
            base_url="http://mcp-demo:8090", trust_env=False, follow_redirects=False
        ) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            request: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": "stack",
                "method": "tools/list",
                "params": {},
            }
            self.assertEqual(client.post("/mcp", json=request).status_code, 401)
            client.headers["Authorization"] = "Bearer apitest-only-mcp-runtime-not-for-deployment"
            initialized = client.post(
                "/mcp",
                json={
                    **request,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "isolated-stack-check", "version": "1"},
                    },
                },
            )
            self.assertEqual(initialized.status_code, 200)
            self.assertEqual(initialized.json()["result"]["protocolVersion"], "2024-11-05")
            self.assertEqual(
                client.post(
                    "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
                ).status_code,
                202,
            )
            response = client.post("/mcp", json=request)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                {tool["name"] for tool in response.json()["result"]["tools"]},
                {"formula_hint", "unit_convert"},
            )
            converted = client.post(
                "/mcp",
                json={
                    **request,
                    "method": "tools/call",
                    "params": {
                        "name": "unit_convert",
                        "arguments": {"question": "将 100 cm 转换为 m"},
                    },
                },
            )
            self.assertEqual(converted.status_code, 200)
            result = converted.json()["result"]
            self.assertFalse(result.get("isError", False))
            self.assertIn("1 m", result["content"][0]["text"])

    def test_internal_only_provider_no_default_egress(self) -> None:
        # A network-isolation check, not an external model request; sends no app data.
        for service in ("db", "api", "gateway", "provider-stub", "qdrant", "mcp-demo"):
            self.assertTrue(socket.gethostbyname(service))
        parsed = urlsplit("http://provider-stub:8000/v1")
        with httpx.Client(trust_env=False) as client:
            self.assertEqual(client.get(f"http://{parsed.netloc}/health").status_code, 200)
        # Inspect container route table: internal Docker network must have no default route.
        with open("/proc/net/route") as routes:
            destinations = [line.split()[1] for line in routes.read().splitlines()[1:]]
        self.assertNotIn("00000000", destinations)


if __name__ == "__main__":
    unittest.main()
