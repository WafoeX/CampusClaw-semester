"""HTTP-only fixture setup and independent OpenAPI/SELECT contract assertions.

No application imports, provider calls, database writes, or cross-operation case dispatch.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, cast

from .clients import Context, parse_sse_chunks
from .support import Checks

PASSWORD = "apitest-account-only"
MISSING = "00000000-0000-0000-0000-000000000001"
REFUSAL = "根据本班资料无法回答该问题"
SKILL: dict[str, Any] = {
    "name": "Synthetic guidance",
    "skill_type": "solution_guidance",
    "instructions": "提供观察提示和追问，不给出最终结论。",
}
AGENT: dict[str, Any] = {
    "name": "Synthetic tutor",
    "description": "Synthetic description",
    "system_prompt": "引导学生逐步观察。",
    "skill_ids": [],
}


def matches(value: Any, schema: dict[str, Any], document: dict[str, Any]) -> bool:
    """Validate the emitted OpenAPI schema subset, independently of application models."""
    if "$ref" in schema:
        return matches(
            value, document["components"]["schemas"][schema["$ref"].split("/")[-1]], document
        )
    if "anyOf" in schema:
        return any(matches(value, choice, document) for choice in schema["anyOf"])
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    kind = schema.get("type")
    if kind == "null":
        return value is None
    if kind == "object":
        if not isinstance(value, dict) or not set(schema.get("required", [])) <= value.keys():
            return False
        value = cast(dict[str, Any], value)
        properties = schema.get("properties", {})
        if (
            type(schema.get("additionalProperties")) is bool
            and not schema["additionalProperties"]
            and not value.keys() <= properties.keys()
        ):
            return False
        return all(
            matches(item, properties[key], document)
            for key, item in value.items()
            if key in properties
        )
    if kind == "array":
        items = cast(list[Any], value)
        if not isinstance(value, list):
            return False
        return schema.get("minItems", 0) <= len(items) <= schema.get("maxItems", 10000) and all(
            matches(item, schema.get("items", {}), document) for item in items
        )
    if kind == "string":
        if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= schema.get(
            "maxLength", 1000000
        ):
            return False
        if schema.get("pattern") and not re.search(schema["pattern"], value):
            return False
        try:
            if schema.get("format") == "uuid":
                uuid.UUID(value)
            if schema.get("format") == "date-time":
                return datetime.fromisoformat(value).tzinfo is not None
        except ValueError:
            return False
    if kind == "integer":
        return type(value) is int and schema.get("minimum", -1e300) <= value <= schema.get(
            "maximum", 1e300
        )
    if kind == "boolean":
        return type(value) is bool
    return True


class Scenario:
    def __init__(self, context: Context, checks: Checks) -> None:
        self.context, self.checks = context, checks
        status, document = context.client.json("GET", "/api/openapi.json")
        checks.require(status == 200 and isinstance(document, dict), "response.schema")
        self.document: dict[str, Any] = document
        self.tokens: dict[str, str] = {}
        self.identities: dict[str, dict[str, Any]] = {}

    def token(self, account: str) -> str:
        if account not in self.tokens:
            self.tokens[account] = self.context.client.login(account, PASSWORD)
        return self.tokens[account]

    def identity(self, account: str) -> dict[str, Any]:
        if account not in self.identities:
            self.identities[account] = self.call("GET", "/api/auth/me", account=account)
        return self.identities[account]

    def call(
        self,
        method: str,
        path: str,
        *,
        account: str | None = "teacher.alpha",
        body: Any = None,
        status: int = 200,
        code: str | None = None,
    ) -> Any:
        response = self.context.client.request(
            method, path, token=self.token(account) if account else None, body=body
        )
        self.checks.require(response.status_code == status, "response.status")
        self.checks.require(
            response.headers.get("content-type", "").split(";")[0] == "application/json",
            "response.media_type",
        )
        value = response.json()
        url = path.split("?")[0]
        operation = next(
            (
                operations[method.lower()]
                for template, operations in self.document["paths"].items()
                if method.lower() in operations
                and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), url)
            ),
            None,
        )
        self.checks.require(
            operation is not None and str(status) in operation["responses"], "response.schema"
        )
        if operation is None:
            raise ValueError("response_contract_missing")
        schema = operation["responses"][str(status)]["content"]["application/json"]["schema"]
        self.checks.require(matches(value, schema, self.document), "response.schema")
        if code:
            self.checks.require(value["detail"]["code"] == code, "response.values")
        return value

    def skill(self, account: str = "teacher.alpha") -> dict[str, Any]:
        result: dict[str, Any] = self.call(
            "POST",
            "/api/skills",
            account=account,
            body={**SKILL, "name": self.context.fixtures.name(uuid.uuid4().hex[:8])},
            status=201,
        )
        return result

    def agent(self, account: str = "teacher.alpha", *, published: bool = False) -> dict[str, Any]:
        skill = self.skill(account)
        agent: dict[str, Any] = self.call(
            "POST",
            "/api/agents",
            account=account,
            body={
                **AGENT,
                "name": self.context.fixtures.name(uuid.uuid4().hex[:8]),
                "skill_ids": [skill["id"]],
            },
            status=201,
        )
        if published:
            result: dict[str, Any] = self.call(
                "POST", f"/api/agents/{agent['id']}/publish", account=account
            )
            return result
        return agent

    def conversation(
        self, *, student: str = "student.alpha", teacher: str = "teacher.alpha"
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        agent = self.agent(teacher, published=True)
        conversation = self.call(
            "POST",
            "/api/conversations",
            account=student,
            body={"agent_id": agent["id"]},
            status=201,
        )
        return conversation, agent

    def skill_rows(self, identifier: str) -> list[dict[str, Any]]:
        return self.context.database.rows(
            "SELECT s.*, r.revision_number, r.name, r.instructions, r.skill_type "
            "FROM skills s JOIN skill_revisions r ON r.id = s.current_revision_id "
            "WHERE s.id = %s",
            (identifier,),
        )

    def agent_rows(self, identifier: str) -> list[dict[str, Any]]:
        return self.context.database.rows(
            "SELECT a.*, r.revision_number, r.name, r.description, r.system_prompt "
            "FROM agents a JOIN agent_revisions r ON r.id = a.current_revision_id "
            "WHERE a.id = %s",
            (identifier,),
        )

    def verify_resource(
        self, resource: dict[str, Any], kind: str, account: str = "teacher.alpha"
    ) -> None:
        rows = (
            self.skill_rows(resource["id"]) if kind == "skills" else self.agent_rows(resource["id"])
        )
        self.checks.require(len(rows) == 1, "database.rows")
        row, identity = rows[0], self.identity(account)
        self.checks.require(
            str(row["class_id"]) == identity["class_id"]
            and str(row["creator_id"]) == identity["user_id"],
            "database.scope",
        )
        for key in ("id", "state", "name", "current_revision_id"):
            self.checks.require(str(row[key]) == str(resource[key]), "database.rows")
        if kind == "skills":
            self.checks.require(
                all(row[key] == resource[key] for key in ("instructions", "skill_type")),
                "database.revisions",
            )
        else:
            self.checks.require(
                all(row[key] == resource[key] for key in ("system_prompt", "description")),
                "database.revisions",
            )
            self.checks.require(
                (str(row["published_revision_id"]) if row["published_revision_id"] else None)
                == resource["published_revision_id"],
                "database.revisions",
            )
            bindings = self.context.database.rows(
                "SELECT b.class_id, b.creator_id, s.skill_id, s.id FROM agent_skill_bindings b "
                "JOIN skill_revisions s ON s.id = b.skill_revision_id "
                "WHERE b.agent_revision_id = %s",
                (resource["current_revision_id"],),
            )
            self.checks.require(
                sorted(str(item["skill_id"]) for item in bindings) == sorted(resource["skill_ids"]),
                "database.bindings",
            )
            self.checks.require(
                all(
                    str(item["class_id"]) == identity["class_id"]
                    and str(item["creator_id"]) == identity["user_id"]
                    for item in bindings
                ),
                "database.scope",
            )

    def conversation_rows(self, identifier: str) -> list[dict[str, Any]]:
        return self.context.database.rows(
            "SELECT * FROM conversations WHERE id = %s", (identifier,)
        )

    def messages(self, identifier: str) -> list[dict[str, Any]]:
        return self.context.database.rows(
            "SELECT * FROM conversation_messages WHERE conversation_id = %s ORDER BY ordinal",
            (identifier,),
        )

    def verify_conversation(self, value: dict[str, Any], account: str = "student.alpha") -> None:
        rows, identity = self.conversation_rows(value["id"]), self.identity(account)
        self.checks.require(len(rows) == 1, "database.rows")
        row = rows[0]
        self.checks.require(
            str(row["student_id"]) == identity["user_id"] == value["student_id"]
            and str(row["class_id"]) == identity["class_id"]
            and str(row["agent_id"]) == value["agent_id"],
            "database.scope",
        )
        self.checks.require(
            row["deleted_at"]
            == (datetime.fromisoformat(value["deleted_at"]) if value["deleted_at"] else None)
            and type(value["creator_retains_audit_access"]) is bool
            and value["creator_retains_audit_access"],
            "database.rows",
        )

    def hidden(
        self,
        method: str,
        path: str,
        missing: str,
        *,
        body: Any = None,
        accounts: tuple[str, ...] = ("teacher.alpha.other", "teacher.beta"),
    ) -> None:
        for account in accounts:
            value = self.call(method, path, account=account, body=body, status=404)
            absent = self.call(method, missing, account=account, body=body, status=404)
            self.checks.require(value == absent, "auth.indistinguishable")

    def stream(
        self, conversation: str, content: str, *, expected: str = "message.completed"
    ) -> list[dict[str, Any]]:
        response = self.context.client.request(
            "POST",
            f"/api/conversations/{conversation}/messages",
            token=self.token("student.alpha"),
            body={"content": content},
        )
        self.checks.require(
            response.status_code == 200
            and response.headers.get("content-type", "").startswith("text/event-stream"),
            "response.media_type",
        )
        events = parse_sse_chunks(response.iter_bytes(chunk_size=7))
        self.checks.require(
            events[0]["event"] == "message.started" and events[-1]["event"] == expected,
            "stream.order",
        )
        media = self.document["paths"]["/api/conversations/{conversation_id}/messages"]["post"][
            "responses"
        ]["200"]["content"]["text/event-stream"]
        self.checks.require(
            all(
                matches(event["data"], media["x-event-schemas"][event["event"]], self.document)
                for event in events
            ),
            "response.schema",
        )
        self.verify_stream(events, content)
        return events

    def verify_stream(self, events: list[dict[str, Any]], content: str) -> None:
        start, end = events[0]["data"], events[-1]["data"]
        rows = self.messages(start["conversation_id"])
        user = [row for row in rows if str(row["id"]) == start["user_message_id"]]
        assistant = [row for row in rows if str(row["id"]) == start["assistant_message_id"]]
        self.checks.require(
            len(user) == len(assistant) == 1
            and user[0]["content"] == content
            and user[0]["state"] == "completed",
            "database.messages",
        )
        row = assistant[0]
        conversation = self.conversation_rows(start["conversation_id"])[0]
        self.checks.require(
            all(
                item["class_id"] == conversation["class_id"]
                and item["student_id"] == conversation["student_id"]
                and item["agent_id"] == conversation["agent_id"]
                for item in (user[0], row)
            ),
            "database.scope",
        )
        self.checks.require(
            row["ordinal"] == user[0]["ordinal"] + 1
            and str(row["applied_agent_revision_id"]) == start["configuration_revision_id"]
            and row["configuration_updated"] == start["configuration_updated"],
            "database.revisions",
        )
        citations = self.context.database.rows(
            "SELECT * FROM message_citations WHERE message_id = %s ORDER BY ordinal",
            (start["assistant_message_id"],),
        )
        if events[-1]["event"] == "message.error":
            self.checks.require(
                row["state"] == "failed"
                and row["content"] is None
                and row["safe_error_code"] == end["code"]
                and not citations
                and row["completed_at"] is not None,
                "database.messages",
            )
        else:
            answer = "".join(
                item["data"]["delta"] for item in events if item["event"] == "answer.delta"
            )
            self.checks.require(
                row["state"] == "completed"
                and row["content"] == answer
                and row["safe_error_code"] is None
                and row["retrieval_mode"] == end["retrieval_mode"]
                and row["completed_at"] == datetime.fromisoformat(end["completed_at"]),
                "database.messages",
            )
            sources = [item["data"]["source"] for item in events if item["event"] == "citation"]
            self.checks.require(
                [item["source_snapshot"] for item in citations] == sources, "database.citations"
            )
            for citation, source in zip(citations, sources, strict=True):
                chunks = self.context.database.rows(
                    "SELECT k.class_id, k.material_id, k.index_version_id, s.active_version_id, "
                    "m.state FROM knowledge_chunks k "
                    "JOIN material_search_states s ON s.material_id = k.material_id "
                    "JOIN materials m ON m.id = k.material_id WHERE k.id = %s",
                    (citation["chunk_id"],),
                )
                self.checks.require(
                    len(chunks) == 1
                    and chunks[0]["class_id"] == conversation["class_id"] == citation["class_id"]
                    and str(chunks[0]["material_id"]) == source["material_id"]
                    and chunks[0]["index_version_id"] == chunks[0]["active_version_id"]
                    and chunks[0]["state"] == "ready",
                    "database.citations",
                )
        self.checks.require(
            [event["data"]["sequence"] for event in events] == list(range(1, len(events) + 1)),
            "stream.sequence",
        )
        self.checks.require(
            all(
                event["data"]["conversation_id"] == start["conversation_id"]
                and event["data"]["user_message_id"] == start["user_message_id"]
                and event["data"]["assistant_message_id"] == start["assistant_message_id"]
                for event in events
            ),
            "stream.identifiers",
        )
        wire = str(events)
        self.checks.require(
            all(
                secret not in wire
                for secret in (
                    *self.tokens.values(),
                    PASSWORD,
                    SKILL["instructions"],
                    AGENT["system_prompt"],
                    "postgresql://",
                    "not-json",
                    "fixture_unavailable",
                    "BETA_CRYSTAL",
                )
            ),
            "safe",
        )
