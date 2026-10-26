"""Supervisor-owned MCP dispatch and durable, monotonic, minimal tool audits.

Only async HTTP is awaited. Short DB transactions release their locks before HTTP;
no generation worker can reach this module's write operations or replay a call.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal
from campusclaw.application.generation import InvalidGenerationOutput
from campusclaw.application.mcp_client import McpClient, McpFailure, compatible_question_schema, obj
from campusclaw.config import Settings
from campusclaw.domain.models import (
    AgentRevision,
    AgentSkillBinding,
    Conversation,
    ConversationMessage,
    McpDiscoveredTool,
    McpServer,
    McpToolCall,
    Skill,
    SkillRevision,
    User,
)
from campusclaw.domain.tool_outcomes import ToolText
from campusclaw.domain.tool_references import REFERENCE
from campusclaw.persistence.database import Database

TOOL_STAGE_SECONDS = 10.0
TOOL_CALL_SECONDS = 3.0


@dataclass(frozen=True)
class ToolReference:
    tool_ref: str
    tool_name: str
    server_id: uuid.UUID | None
    invalid: bool = False


@dataclass(frozen=True)
class ToolPlan:
    question: str
    references: tuple[ToolReference, ...]


@dataclass(frozen=True)
class FinalCall:
    tool_ref: str
    status: Literal["ok", "denied", "error"]
    code: str
    text: str | None = None

    def metadata(self) -> dict[str, str]:
        return {"tool_ref": self.tool_ref, "status": self.status, "code": self.code}


@dataclass(frozen=True)
class Permit:
    call_id: uuid.UUID
    base_url: str
    tool_name: str


def _reference(value: object) -> ToolReference | None:
    if value == "knowledge_search":
        return None
    entry = obj(value)
    reference = entry.get("reference") if entry is not None else value
    if not isinstance(reference, str) or REFERENCE.fullmatch(reference) is None:
        return ToolReference("invalid_tool_reference", "", None, True)
    name = reference.split("@", 1)[0]
    try:
        if entry is None or entry.get("tool_name") != name:
            raise ValueError
        server_id = uuid.UUID(str(entry.get("server_id")))
    except ValueError:
        return ToolReference(reference, name, None, True)
    return ToolReference(reference, name, server_id)


def _final(call: McpToolCall, *, text: str | None = None) -> FinalCall:
    if call.execution_state != "finalized" or call.status not in {"ok", "denied", "error"}:
        raise InvalidGenerationOutput("generation_failed")
    return FinalCall(
        call.tool_ref,
        cast(Literal["ok", "denied", "error"], call.status),
        call.code or "interrupted",
        text if call.status == "ok" else None,
    )


def snapshot_calls(session: Session, assistant: ConversationMessage) -> list[dict[str, str]]:
    """Never expose pending, arguments, raw results, or remote errors."""
    session.flush()
    calls = session.scalars(
        select(McpToolCall)
        .where(
            McpToolCall.assistant_message_id == assistant.id,
            McpToolCall.class_id == assistant.class_id,
            McpToolCall.execution_state == "finalized",
        )
        .order_by(McpToolCall.tool_ref)
    )
    snapshot = [_final(call).metadata() for call in calls]
    assistant.tool_calls = snapshot
    return snapshot


class McpToolStage:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        principal: Principal,
        conversation_id: uuid.UUID,
        user_message_id: uuid.UUID,
        assistant_id: uuid.UUID,
        *,
        client: McpClient | None = None,
    ) -> None:
        self.database = database
        self.principal = principal
        self.conversation_id = conversation_id
        self.user_message_id = user_message_id
        self.assistant_id = assistant_id
        self.client = client or McpClient(settings)
        self.plan: ToolPlan | None = None

    def _assistant(self, session: Session) -> ConversationMessage:
        assistant = session.scalar(
            select(ConversationMessage)
            .where(
                ConversationMessage.id == self.assistant_id,
                ConversationMessage.conversation_id == self.conversation_id,
                ConversationMessage.class_id == self.principal.class_id,
                ConversationMessage.student_id == self.principal.user_id,
                ConversationMessage.role == "assistant",
            )
            .with_for_update()
        )
        if assistant is None:
            raise InvalidGenerationOutput("generation_invalid")
        return assistant

    def prepare(self) -> ToolPlan:
        with self.database.transaction() as session:
            assistant = self._assistant(session)
            if assistant.state != "processing":
                raise InvalidGenerationOutput("generation_failed")
            user = session.scalar(
                select(ConversationMessage).where(
                    ConversationMessage.id == self.user_message_id,
                    ConversationMessage.conversation_id == self.conversation_id,
                    ConversationMessage.class_id == self.principal.class_id,
                    ConversationMessage.student_id == self.principal.user_id,
                    ConversationMessage.role == "user",
                    ConversationMessage.ordinal == assistant.ordinal - 1,
                )
            )
            revision = session.scalar(
                select(AgentRevision).where(
                    AgentRevision.id == assistant.applied_agent_revision_id,
                    AgentRevision.agent_id == assistant.agent_id,
                    AgentRevision.class_id == assistant.class_id,
                )
            )
            if user is None or not user.content or revision is None:
                raise InvalidGenerationOutput("generation_invalid")
            skills = session.scalars(
                select(SkillRevision)
                .join(AgentSkillBinding, AgentSkillBinding.skill_revision_id == SkillRevision.id)
                .join(Skill, Skill.id == SkillRevision.skill_id)
                .where(
                    AgentSkillBinding.agent_revision_id == revision.id,
                    SkillRevision.class_id == assistant.class_id,
                    SkillRevision.creator_id == revision.creator_id,
                    Skill.state == "active",
                )
            )
            references: dict[str, ToolReference] = {}
            for skill in skills:
                for value in skill.tools:
                    reference = _reference(value)
                    if reference is None:
                        continue
                    old = references.get(reference.tool_ref)
                    if old is not None and old != reference:
                        reference = ToolReference(
                            reference.tool_ref, reference.tool_name, None, True
                        )
                    references[reference.tool_ref] = reference
            self.plan = ToolPlan(
                user.content[:2000], tuple(references[key] for key in sorted(references))
            )
            return self.plan

    def _active(self, session: Session) -> bool:
        # Same lock order for dispatch and result acceptance: assistant, user,
        # conversation, server. No locks survive a network await.
        user = session.scalar(
            select(User)
            .where(
                User.id == self.principal.user_id,
                User.class_id == self.principal.class_id,
                User.is_active.is_(True),
                User.role == "student",
            )
            .with_for_update()
        )
        conversation = session.scalar(
            select(Conversation)
            .where(
                Conversation.id == self.conversation_id,
                Conversation.class_id == self.principal.class_id,
                Conversation.student_id == self.principal.user_id,
                Conversation.deleted_at.is_(None),
            )
            .with_for_update()
        )
        return user is not None and conversation is not None

    def _server(self, session: Session, reference: ToolReference) -> McpServer | None:
        return session.scalar(
            select(McpServer)
            .where(
                McpServer.id == reference.server_id,
                McpServer.class_id == self.principal.class_id,
                McpServer.name == reference.tool_ref.split("@")[-1],
            )
            .with_for_update()
        )

    def start(
        self,
        reference: ToolReference,
        *,
        forced: tuple[Literal["denied", "error"], str] | None = None,
    ) -> Permit | FinalCall:
        with self.database.transaction() as session:
            assistant = self._assistant(session)
            if assistant.state != "processing":
                raise InvalidGenerationOutput("generation_failed")
            old = session.scalar(
                select(McpToolCall).where(
                    McpToolCall.assistant_message_id == assistant.id,
                    McpToolCall.tool_ref == reference.tool_ref,
                    McpToolCall.class_id == self.principal.class_id,
                )
            )
            if old is not None:
                # Never replay an existing dispatch, including after a crash.
                return _final(old)
            call = McpToolCall(
                id=uuid.uuid4(),
                class_id=self.principal.class_id,
                user_id=self.principal.user_id,
                conversation_id=self.conversation_id,
                assistant_message_id=assistant.id,
                tool_ref=reference.tool_ref,
            )
            denied: str | None = None
            base_url = ""
            if forced is None:
                if reference.invalid:
                    denied = "invalid_binding"
                elif not self._active(session):
                    denied = "not_authorized"
                else:
                    server = self._server(session, reference)
                    if server is None:
                        denied = "not_authorized"
                    else:
                        call.server_id, call.generation = server.id, server.connection_generation
                        base_url = server.base_url
                        if server.state != "connected":
                            denied = "server_disconnected"
                        else:
                            tool = session.scalar(
                                select(McpDiscoveredTool).where(
                                    McpDiscoveredTool.server_id == server.id,
                                    McpDiscoveredTool.class_id == self.principal.class_id,
                                    McpDiscoveredTool.generation == server.connection_generation,
                                    McpDiscoveredTool.name == reference.tool_name,
                                )
                            )
                            if tool is None:
                                denied = "tool_not_discovered"
                            elif not compatible_question_schema(tool.input_schema):
                                denied = "tool_schema_unsupported"
                            else:
                                try:
                                    self.client.credential(base_url)
                                except McpFailure:
                                    denied = "credential_unavailable"
            session.add(call)
            if denied is not None or forced is not None:
                call.execution_state = "finalized"
                call.status, call.code = forced if forced is not None else ("denied", denied)
                call.completed_at = datetime.now(UTC)
                snapshot_calls(session, assistant)
                return _final(call)
            session.flush()
            permit = Permit(call.id, base_url, reference.tool_name)
        # Commit is the dispatch linearization point. A failed commit raises
        # before this permit can reach the async HTTP caller.
        return permit

    def finish(
        self, call_id: uuid.UUID, *, text: str | None = None, code: str | None = None
    ) -> FinalCall:
        with self.database.transaction() as session:
            assistant = self._assistant(session)
            call = session.scalar(
                select(McpToolCall)
                .where(
                    McpToolCall.id == call_id,
                    McpToolCall.class_id == self.principal.class_id,
                    McpToolCall.assistant_message_id == assistant.id,
                )
                .with_for_update()
            )
            if call is None:
                raise InvalidGenerationOutput("generation_failed")
            if call.execution_state == "finalized":
                return _final(call)  # A late completion cannot replace any terminal outcome.
            status: Literal["ok", "denied", "error"] = "error" if code is not None else "ok"
            if assistant.state != "processing":
                status, code = "error", "interrupted"
            elif not self._active(session):
                status, code = "denied", "not_authorized"
            else:
                server = session.scalar(
                    select(McpServer)
                    .where(
                        McpServer.id == call.server_id,
                        McpServer.class_id == self.principal.class_id,
                    )
                    .with_for_update()
                )
                if (
                    server is None
                    or server.state != "connected"
                    or server.connection_generation != call.generation
                ):
                    status, code = "denied", "connection_invalidated"
                elif code == "credential_unavailable":
                    status = "denied"
            if status == "ok" and not text:
                status, code = "error", "invalid_tool_result"
            call.execution_state, call.status, call.code = "finalized", status, code or "ok"
            call.completed_at = datetime.now(UTC)
            snapshot_calls(session, assistant)
            outcome = _final(call, text=text)
        return outcome

    def interrupt(self, *, code: str = "interrupted") -> None:
        """Close only existing pending rows, without any remote replay."""
        with self.database.transaction() as session:
            assistant = self._assistant(session)
            pending = session.scalars(
                select(McpToolCall)
                .where(
                    McpToolCall.assistant_message_id == assistant.id,
                    McpToolCall.class_id == self.principal.class_id,
                    McpToolCall.execution_state == "pending",
                )
                .with_for_update()
            )
            for call in pending:
                call.execution_state, call.status, call.code = "finalized", "error", code
                call.completed_at = datetime.now(UTC)
            snapshot_calls(session, assistant)

    async def run(self) -> tuple[ToolText, ...]:
        plan = self.prepare()
        deadline = asyncio.get_running_loop().time() + TOOL_STAGE_SECONDS
        texts: list[ToolText] = []
        try:
            for reference in plan.references:
                remaining = deadline - asyncio.get_running_loop().time()
                forced: tuple[Literal["denied", "error"], str] | None = None
                if len(plan.references) > 8:
                    forced = ("denied", "call_limit_exceeded")
                elif remaining <= 0:
                    forced = ("error", "tool_budget_exceeded")
                permit = self.start(reference, forced=forced)
                if isinstance(permit, FinalCall):
                    continue
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self.finish(permit.call_id, code="tool_timeout")
                    continue
                try:
                    async with asyncio.timeout(min(TOOL_CALL_SECONDS, remaining)):
                        text = await self.client.call(
                            permit.base_url, permit.tool_name, plan.question
                        )
                    outcome = self.finish(permit.call_id, text=text)
                except TimeoutError:
                    outcome = self.finish(permit.call_id, code="tool_timeout")
                except McpFailure as error:
                    outcome = self.finish(permit.call_id, code=error.code)
                if outcome.status == "ok" and outcome.text is not None:
                    texts.append(ToolText(outcome.tool_ref, outcome.text))
        except asyncio.CancelledError:
            self.interrupt(code="tool_timeout")
            for reference in plan.references:
                self.start(reference, forced=("error", "interrupted"))
            raise
        return tuple(texts)


def recover_pending_mcp(database: Database, settings: Settings) -> int:
    """Startup recovery for interrupted MCP turns only; never resend HTTP requests."""
    from campusclaw.application.conversations import ConversationService

    recovered = 0
    with database.transaction() as session:
        identities = list(
            session.scalars(
                select(McpToolCall.assistant_message_id)
                .where(McpToolCall.execution_state == "pending")
                .distinct()
            )
        )
        for identity in sorted(identities):
            assistant = session.scalar(
                select(ConversationMessage)
                .where(ConversationMessage.id == identity)
                .with_for_update()
            )
            if assistant is None:
                continue
            pending = session.scalars(
                select(McpToolCall)
                .where(
                    McpToolCall.assistant_message_id == assistant.id,
                    McpToolCall.class_id == assistant.class_id,
                    McpToolCall.execution_state == "pending",
                )
                .with_for_update()
            )
            for call in pending:
                call.execution_state, call.status, call.code = "finalized", "error", "interrupted"
                call.completed_at = datetime.now(UTC)
                recovered += 1
            snapshot_calls(session, assistant)
            ConversationService(settings).fail_turn(session, assistant, code="generation_failed")
    return recovered
