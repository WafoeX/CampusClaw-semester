"""Disconnect-independent bounded work; only the supervising task writes terminal state."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from campusclaw.api.dependencies import Principal
from campusclaw.api.schemas import CitationSource, ToolCallStatus
from campusclaw.application.chat import ChatResult, ChatService
from campusclaw.application.conversations import ConversationService
from campusclaw.application.generation import (
    REFUSAL_ANSWER,
    InvalidGenerationOutput,
    reauthorize_evidence,
    source_response,
)
from campusclaw.application.mcp_execution import McpToolStage
from campusclaw.application.providers import ProviderFailure
from campusclaw.config import Settings
from campusclaw.domain.models import ConversationMessage, User
from campusclaw.domain.tool_outcomes import ToolText
from campusclaw.persistence.database import Database
from campusclaw.persistence.knowledge import KnowledgeRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnOutcome:
    result: ChatResult | None = None
    answer: str = ""
    sources: tuple[CitationSource, ...] = ()
    completed_at: datetime | None = None
    code: str | None = None
    retryable: bool = True
    tool_calls: tuple[ToolCallStatus, ...] = ()


def _generate(
    database: Database,
    settings: Settings,
    principal: Principal,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    assistant_id: uuid.UUID,
    tool_results: tuple[ToolText, ...] = (),
) -> ChatResult:
    with database.session_factory() as session:
        service = ConversationService(settings)
        conversation = service.read_for_student(session, principal, conversation_id)
        user = session.get(ConversationMessage, user_id)
        assistant = session.get(ConversationMessage, assistant_id)
        if user is None or assistant is None or user.content is None:
            raise InvalidGenerationOutput("generation_invalid")
        history = service.history(session, conversation, before_ordinal=user.ordinal)
        chat = ChatService(settings)
        try:
            return chat.generate(
                session,
                conversation=conversation,
                question=user.content,
                history=history,
                revision_id=assistant.applied_agent_revision_id,
                configuration_updated=assistant.configuration_updated,
                tool_results=tool_results,
            )
        finally:
            chat.close()


def _finish(
    database: Database,
    settings: Settings,
    principal: Principal,
    assistant_id: uuid.UUID,
    result: ChatResult | None,
    code: str | None,
) -> TurnOutcome:
    with database.session_factory() as session:
        assistant = session.scalar(
            select(ConversationMessage)
            .where(
                ConversationMessage.id == assistant_id,
                ConversationMessage.class_id == principal.class_id,
                ConversationMessage.student_id == principal.user_id,
            )
            .with_for_update()
        )
        if assistant is None:
            raise InvalidGenerationOutput("generation_invalid")
        calls = tuple(ToolCallStatus.model_validate(entry) for entry in assistant.tool_calls)
        if assistant.state != "processing":
            return TurnOutcome(
                code=assistant.safe_error_code or "generation_failed", tool_calls=calls
            )
        service = ConversationService(settings)
        if result is not None:
            current_user = session.scalar(
                select(User).where(
                    User.id == principal.user_id,
                    User.class_id == principal.class_id,
                    User.is_active.is_(True),
                    User.role == "student",
                )
            )
            if current_user is None or result.revision_id != assistant.applied_agent_revision_id:
                code = "source_unavailable"
            else:
                try:
                    reauthorize_evidence(
                        session,
                        class_id=principal.class_id,
                        evidence=result.evidence,
                        citation_ids=result.parsed.citation_ids,
                        repository=KnowledgeRepository(),
                    )
                except InvalidGenerationOutput:
                    code = "source_unavailable"
            if code is None:
                answer = result.parsed.answer or REFUSAL_ANSWER
                service.complete_turn(
                    session,
                    assistant,
                    answer=answer,
                    retrieval_mode=result.retrieval_mode,
                    evidence=result.evidence,
                    citation_ids=result.parsed.citation_ids,
                )
                sources = tuple(
                    CitationSource.model_validate(source_response(item))
                    for source_id in result.parsed.citation_ids
                    for item in result.evidence
                    if item.source_id == source_id
                )
                completed_at = assistant.completed_at
                session.commit()
                return TurnOutcome(result, answer, sources, completed_at, tool_calls=calls)
        service.fail_turn(session, assistant, code=code or "generation_failed")
        session.commit()
        return TurnOutcome(
            code=code or "generation_failed",
            retryable=code != "generation_invalid",
            tool_calls=calls,
        )


async def execute_turn(
    database: Database,
    settings: Settings,
    principal: Principal,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    assistant_id: uuid.UUID,
) -> TurnOutcome:
    result: ChatResult | None = None
    code: str | None = None
    stage = McpToolStage(database, settings, principal, conversation_id, user_id, assistant_id)
    try:
        async with asyncio.timeout(settings.SSE_TASK_TIMEOUT_SECONDS):
            # MCP runs only in this supervisor, before the no-evidence early return.
            # Its finalized text snapshots are immutable and ephemeral in the worker.
            tools = await stage.run()
            result = await asyncio.to_thread(
                _generate,
                database,
                settings,
                principal,
                conversation_id,
                user_id,
                assistant_id,
                tools,
            )
    except TimeoutError:
        code = "generation_timeout"
    except InvalidGenerationOutput:
        code = "generation_invalid"
    except ProviderFailure:
        code = "answer_generation_unavailable"
    except asyncio.CancelledError:
        code = "generation_failed"
    except Exception:
        # Never log exception repr/traceback: provider/SQL exceptions can carry inputs.
        code = "generation_failed"
    try:
        stage.interrupt()  # Independent commit; never await or replay abandoned HTTP calls.
    except Exception:
        code = "generation_failed"
    outcome = await asyncio.to_thread(
        _finish,
        database,
        settings,
        principal,
        assistant_id,
        result,
        code,
    )
    logger.info("chat.turn.finished code=%s", outcome.code or "completed")
    return outcome
