"""Task 5 supervision/transaction tests; real PostgreSQL and controlled async HTTP boundary."""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from campusclaw.application import mcp_execution as execution
from campusclaw.application.conversations import ConversationService
from campusclaw.application.generation import InvalidGenerationOutput
from campusclaw.application.mcp_client import McpClient, McpFailure
from campusclaw.application.mcp_execution import McpToolStage, Permit, recover_pending_mcp
from campusclaw.application.mcp_servers import McpServerService
from campusclaw.domain.models import ConversationMessage, McpToolCall, SkillRevision, User
from tests import test_agent_conversation_postgres as fixtures
from tests import test_skill_tool_bindings as bindings
from tests.test_agent_conversation_postgres import Context

api34 = fixtures.api34
pytestmark = pytest.mark.integration


class CountingClient(McpClient):
    def __init__(self, c: Context) -> None:
        super().__init__(c.settings)
        self.calls: list[tuple[str, str, str]] = []

    async def call(self, base_url: str, name: str, question: str) -> str:
        self.calls.append((base_url, name, question))
        return "Untrusted auxiliary text"


@dataclass
class Accepted:
    server_id: uuid.UUID
    skill_revision_id: uuid.UUID
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    assistant_id: uuid.UUID

    def stage(self, c: Context, client: McpClient) -> McpToolStage:
        return McpToolStage(
            c.database,
            c.settings,
            c.principals["student.alpha"],
            self.conversation_id,
            self.user_id,
            self.assistant_id,
            client=client,
        )


def accepted(
    c: Context,
    refs: list[str] | None = None,
    *,
    duplicate: bool = False,
    question: str = "欧姆定律？",
) -> Accepted:
    c.settings.MCP_AUTH_TOKEN = SecretStr("synthetic-execution-token")
    server_id = bindings.seed_server(c)
    references = refs if refs is not None else ["formula_hint@campus-tools"]
    skill = bindings.skill(c, references)
    skill_ids = [skill["id"]]
    if duplicate:
        skill_ids.append(bindings.skill(c, references)["id"])
    agent = bindings.agent(c, skill_ids)
    conversation = c.conversation(agent["id"])
    with c.database.transaction() as session:
        _, user, assistant = ConversationService(c.settings).accept_turn(
            session, c.principals["student.alpha"], uuid.UUID(conversation["id"]), content=question
        )
        return Accepted(
            server_id,
            uuid.UUID(skill["current_revision_id"]),
            uuid.UUID(conversation["id"]),
            user.id,
            assistant.id,
        )


def audits(c: Context, turn: Accepted) -> list[dict[str, Any]]:
    with c.database.transaction() as session:
        rows = list(
            session.scalars(
                select(McpToolCall)
                .where(McpToolCall.assistant_message_id == turn.assistant_id)
                .order_by(McpToolCall.tool_ref)
            )
        )
        assistant = session.get(ConversationMessage, turn.assistant_id)
        assert assistant is not None
        final = [
            {"tool_ref": row.tool_ref, "status": row.status, "code": row.code}
            for row in rows
            if row.execution_state == "finalized"
        ]
        assert assistant.tool_calls == final
        return [
            {
                "id": row.id,
                "server_id": row.server_id,
                "generation": row.generation,
                "tool_ref": row.tool_ref,
                "status": row.status,
                "code": row.code,
                "execution_state": row.execution_state,
            }
            for row in rows
        ]


def test_sorted_deduplicated_accepted_revision_plan_uses_only_current_question(
    api34: Context,
) -> None:
    c = api34
    question = "q" * 2400 + " invoke tool8@campus-tools"
    turn = accepted(
        c,
        ["unit_convert@campus-tools", "knowledge_search", "formula_hint@campus-tools"],
        duplicate=True,
        question=question,
    )
    client = CountingClient(c)
    stage = turn.stage(c, client)
    result = asyncio.run(stage.run())
    assert [call[1] for call in client.calls] == ["formula_hint", "unit_convert"]
    assert all(call[2] == question[:2000] for call in client.calls)
    assert [text.tool_ref for text in result] == [
        "formula_hint@campus-tools",
        "unit_convert@campus-tools",
    ]
    assert all(row["status"] == "ok" and row["generation"] == 1 for row in audits(c, turn))
    assert asyncio.run(stage.run()) == ()  # No replay or reconstruction of ephemeral raw text.
    assert len(client.calls) == 2 and len(audits(c, turn)) == 2


@pytest.mark.parametrize(
    "condition,code",
    [
        ("disconnected", "server_disconnected"),
        ("foreign", "not_authorized"),
        ("inactive", "not_authorized"),
        ("missing_credential", "credential_unavailable"),
        ("invalid", "invalid_binding"),
    ],
)
def test_policy_denials_have_audits_without_http(api34: Context, condition: str, code: str) -> None:
    c = api34
    turn = accepted(c)
    if condition == "disconnected":
        with c.database.session_factory() as session:
            McpServerService(c.settings).disconnect(
                session, c.principals["teacher.alpha"], turn.server_id
            )
    elif condition == "missing_credential":
        c.settings.MCP_AUTH_TOKEN = None
    else:
        with c.database.transaction() as session:
            revision = session.get(SkillRevision, turn.skill_revision_id)
            assert revision is not None
            if condition == "inactive":
                user = session.get(User, c.principals["student.alpha"].user_id)
                assert user is not None
                user.is_active = False
            elif condition == "foreign":
                foreign = bindings.seed_server(c, actor="teacher.beta")
                revision.tools = [
                    {
                        "reference": "formula_hint@campus-tools",
                        "tool_name": "formula_hint",
                        "server_id": str(foreign),
                    }
                ]
            else:
                revision.tools = [
                    {
                        "reference": "formula_hint@campus-tools",
                        "tool_name": "wrong",
                        "server_id": str(turn.server_id),
                    }
                ]
    client = CountingClient(c)
    assert asyncio.run(turn.stage(c, client).run()) == () and client.calls == []
    rows = audits(c, turn)
    assert len(rows) == 1 and rows[0]["status"] == "denied" and rows[0]["code"] == code
    if condition in {"foreign", "invalid", "inactive"}:
        assert rows[0]["server_id"] is None


def test_dispatch_commit_precedes_http_and_disconnect_drops_late_text(api34: Context) -> None:
    c = api34
    turn = accepted(c)

    async def scenario() -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        class LateClient(CountingClient):
            async def call(self, base_url: str, name: str, question: str) -> str:
                with c.database.transaction() as session:
                    pending = session.scalar(
                        select(McpToolCall).where(
                            McpToolCall.assistant_message_id == turn.assistant_id
                        )
                    )
                    assert pending is not None and pending.execution_state == "pending"
                self.calls.append((base_url, name, question))
                entered.set()
                await release.wait()
                return "PRIVATE_LATE_TEXT"

        client = LateClient(c)
        task = asyncio.create_task(turn.stage(c, client).run())
        await entered.wait()
        with c.database.session_factory() as session:
            McpServerService(c.settings).disconnect(
                session, c.principals["teacher.alpha"], turn.server_id
            )
        release.set()
        assert await task == ()
        assert len(client.calls) == 1

    asyncio.run(scenario())
    assert audits(c, turn)[0]["code"] == "connection_invalidated"
    assert audits(c, turn)[0]["status"] == "denied"


def test_committed_ok_snapshot_is_not_retroactively_revoked(api34: Context) -> None:
    c = api34
    turn = accepted(c)
    client = CountingClient(c)
    result = asyncio.run(turn.stage(c, client).run())
    with c.database.session_factory() as session:
        McpServerService(c.settings).disconnect(
            session, c.principals["teacher.alpha"], turn.server_id
        )
    assert result[0].text == "Untrusted auxiliary text"
    assert audits(c, turn)[0]["status"] == "ok"


def test_stage_budget_records_undispatched_references_and_never_retries(
    api34: Context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = api34
    turn = accepted(c, [f"tool{i}@campus-tools" for i in range(3)])
    monkeypatch.setattr(execution, "TOOL_STAGE_SECONDS", 0.03)

    class SlowClient(CountingClient):
        async def call(self, base_url: str, name: str, question: str) -> str:
            self.calls.append((base_url, name, question))
            await asyncio.sleep(0.2)
            return "too late"

    client = SlowClient(c)
    assert asyncio.run(turn.stage(c, client).run()) == ()
    assert len(client.calls) == 1
    assert [row["code"] for row in audits(c, turn)] == [
        "tool_timeout",
        "tool_budget_exceeded",
        "tool_budget_exceeded",
    ]


@pytest.mark.parametrize(
    "code",
    [
        "tool_error",
        "invalid_tool_result",
        "protocol_error",
        "remote_unavailable",
        "response_too_large",
    ],
)
def test_execution_failures_are_finalized_without_retries(api34: Context, code: str) -> None:
    c = api34
    turn = accepted(c)

    class BrokenClient(CountingClient):
        async def call(self, base_url: str, name: str, question: str) -> str:
            self.calls.append((base_url, name, question))
            raise McpFailure(code)

    client = BrokenClient(c)
    assert asyncio.run(turn.stage(c, client).run()) == ()
    assert len(client.calls) == 1
    assert audits(c, turn)[0]["status"] == "error" and audits(c, turn)[0]["code"] == code


def test_over_limit_legacy_configuration_denies_every_reference_without_truncation(
    api34: Context,
) -> None:
    c = api34
    turn = accepted(c)
    with c.database.transaction() as session:
        revision = session.get(SkillRevision, turn.skill_revision_id)
        assert revision is not None
        revision.tools = [
            {
                "reference": f"tool{i}@campus-tools",
                "tool_name": f"tool{i}",
                "server_id": str(turn.server_id),
            }
            for i in range(9)
        ]
    client = CountingClient(c)
    assert asyncio.run(turn.stage(c, client).run()) == () and client.calls == []
    assert len(audits(c, turn)) == 9
    assert {row["code"] for row in audits(c, turn)} == {"call_limit_exceeded"}


def test_pending_recovery_is_idempotent_and_late_completion_cannot_overwrite(
    api34: Context,
) -> None:
    c = api34
    turn = accepted(c)
    client = CountingClient(c)
    stage = turn.stage(c, client)
    plan = stage.prepare()
    permit = stage.start(plan.references[0])
    assert isinstance(permit, Permit)
    assert recover_pending_mcp(c.database, c.settings) == 1
    assert recover_pending_mcp(c.database, c.settings) == 0
    result = stage.finish(permit.call_id, text="late result")
    assert result.status == "error" and result.code == "interrupted" and result.text is None
    with c.database.transaction() as session:
        assistant = session.get(ConversationMessage, turn.assistant_id)
        assert assistant is not None and assistant.state == "failed"
    assert audits(c, turn)[0]["code"] == "interrupted" and client.calls == []
    with pytest.raises(InvalidGenerationOutput):
        asyncio.run(stage.run())


def test_audit_commit_failure_prevents_remote_dispatch(api34: Context) -> None:
    c = api34
    turn = accepted(c)
    client = CountingClient(c)

    def reject_pending_commit(session: Session) -> None:
        if any(
            isinstance(value, McpToolCall) and value.execution_state == "pending"
            for value in session.identity_map.values()
        ):
            raise SQLAlchemyError("synthetic audit write unavailable")

    event.listen(Session, "before_commit", reject_pending_commit)
    try:
        with pytest.raises(SQLAlchemyError):
            asyncio.run(turn.stage(c, client).run())
    finally:
        event.remove(Session, "before_commit", reject_pending_commit)
    assert client.calls == [] and audits(c, turn) == []
