"""Authorized conversation lifecycle and durable turn persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal
from campusclaw.api.schemas import CitationSource
from campusclaw.application.agents import AgentService, MissingAgentError
from campusclaw.config import Settings
from campusclaw.domain.models import (
    Conversation,
    ConversationMessage,
    ConversationMessageRole,
    ConversationMessageState,
    MessageCitation,
    User,
    UserRole,
)
from campusclaw.persistence.conversations import ConversationRepository

if TYPE_CHECKING:
    from campusclaw.application.generation import EvidenceItem


class MissingConversationError(LookupError):
    """Existence-hiding error for inaccessible or deleted conversations."""


class TurnInProgressError(RuntimeError):
    """Only one accepted assistant turn may be processing at a time."""


class ConversationRateLimitError(RuntimeError):
    """The authenticated student's bounded request budget is exhausted."""


class ConversationService:
    def __init__(
        self,
        settings: Settings,
        repository: ConversationRepository | None = None,
        agent_service: AgentService | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository or ConversationRepository()
        self._agents = agent_service or AgentService(settings)

    def create(
        self, session: Session, principal: Principal, *, agent_id: uuid.UUID
    ) -> Conversation:
        self._require_student(principal)
        self._agents.require_published_for_student(
            session, class_id=principal.class_id, agent_id=agent_id
        )
        conversation = Conversation(
            id=uuid.uuid4(),
            class_id=principal.class_id,
            student_id=principal.user_id,
            agent_id=agent_id,
        )
        session.add(conversation)
        session.flush()
        return conversation

    def list_for_student(self, session: Session, principal: Principal) -> list[Conversation]:
        self._require_student(principal)
        return self._repository.list_for_student(
            session, class_id=principal.class_id, student_id=principal.user_id
        )

    def read_for_student(
        self, session: Session, principal: Principal, conversation_id: uuid.UUID
    ) -> Conversation:
        self._require_student(principal)
        conversation = self._repository.get_for_student(
            session,
            class_id=principal.class_id,
            student_id=principal.user_id,
            conversation_id=conversation_id,
        )
        if conversation is None:
            raise MissingConversationError()
        return conversation

    def read(
        self, session: Session, principal: Principal, conversation_id: uuid.UUID
    ) -> Conversation:
        if principal.role is UserRole.STUDENT:
            return self.read_for_student(session, principal, conversation_id)
        self._require_teacher(principal)
        conversation = self._repository.get_for_creator(
            session,
            conversation_id=conversation_id,
            creator_id=principal.user_id,
            class_id=principal.class_id,
        )
        if conversation is None:
            raise MissingConversationError()
        return conversation

    def soft_delete(
        self, session: Session, principal: Principal, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = self.read_for_student(session, principal, conversation_id)
        conversation.deleted_at = datetime.now(UTC)
        session.flush()
        return conversation

    def list_for_creator(
        self,
        session: Session,
        principal: Principal,
        agent_id: uuid.UUID,
        *,
        deleted: bool | None = None,
    ) -> list[Conversation]:
        self._require_teacher(principal)
        try:
            self._agents.read(session, principal, agent_id)
        except MissingAgentError:
            raise MissingConversationError() from None
        return self._repository.list_for_agent_creator(
            session,
            agent_id=agent_id,
            creator_id=principal.user_id,
            class_id=principal.class_id,
            deleted=deleted,
        )

    def read_for_creator(
        self,
        session: Session,
        principal: Principal,
        agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        self._require_teacher(principal)
        try:
            self._agents.read(session, principal, agent_id)
        except MissingAgentError:
            raise MissingConversationError() from None
        conversation = self._repository.get_for_agent_creator(
            session,
            conversation_id=conversation_id,
            agent_id=agent_id,
            creator_id=principal.user_id,
            class_id=principal.class_id,
        )
        if conversation is None:
            raise MissingConversationError()
        return conversation

    def messages(self, session: Session, conversation: Conversation) -> list[ConversationMessage]:
        return self._repository.messages(session, conversation=conversation)

    def history(
        self, session: Session, conversation: Conversation, *, before_ordinal: int = 2**63 - 1
    ) -> list[ConversationMessage]:
        """Return a deterministic completed suffix, bounded in SQL and in characters."""
        completed = self._repository.history(
            session,
            conversation=conversation,
            before_ordinal=before_ordinal,
            limit=self._settings.CONVERSATION_HISTORY_MAX_MESSAGES,
        )
        result: list[ConversationMessage] = []
        used = 0
        for message in completed:
            text = message.content or ""
            if len(result) >= self._settings.CONVERSATION_HISTORY_MAX_MESSAGES:
                break
            if used + len(text) > self._settings.CONVERSATION_HISTORY_MAX_CHARS:
                break
            result.append(message)
            used += len(text)
        result.reverse()
        return result

    def accept_turn(
        self,
        session: Session,
        principal: Principal,
        conversation_id: uuid.UUID,
        *,
        content: str,
    ) -> tuple[Conversation, ConversationMessage, ConversationMessage]:
        self._require_student(principal)
        clean = content.strip()
        if (
            not clean
            or len(clean) > self._settings.CONVERSATION_MESSAGE_MAX_CHARS
            or "\x00" in clean
        ):
            raise ValueError("invalid message")
        try:
            clean.encode("utf-8")
        except UnicodeError:
            raise ValueError("invalid message") from None
        # Serialize each student's rate check across conversations and API workers.
        current_user = session.scalar(
            select(User)
            .where(
                User.id == principal.user_id,
                User.class_id == principal.class_id,
                User.is_active.is_(True),
                User.role == UserRole.STUDENT.value,
            )
            .with_for_update()
        )
        if current_user is None:
            raise MissingConversationError()
        conversation = self._repository.get_for_student(
            session,
            class_id=principal.class_id,
            student_id=principal.user_id,
            conversation_id=conversation_id,
            lock=True,
        )
        if conversation is None:
            raise MissingConversationError()
        agent = self._agents.require_published_for_student(
            session, class_id=principal.class_id, agent_id=conversation.agent_id
        )
        if self._repository.has_processing_turn(session, conversation_id=conversation.id):
            raise TurnInProgressError()
        recent = session.scalar(
            select(func.count())
            .select_from(ConversationMessage)
            .where(
                ConversationMessage.student_id == principal.user_id,
                ConversationMessage.class_id == principal.class_id,
                ConversationMessage.role == ConversationMessageRole.USER.value,
                ConversationMessage.created_at >= datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        if (recent or 0) >= self._settings.CONVERSATION_RATE_LIMIT_PER_MINUTE:
            raise ConversationRateLimitError()
        previous_revision = session.scalar(
            select(ConversationMessage.applied_agent_revision_id)
            .where(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.role == ConversationMessageRole.ASSISTANT.value,
            )
            .order_by(ConversationMessage.ordinal.desc())
            .limit(1)
        )
        maximum = session.scalar(
            select(func.max(ConversationMessage.ordinal)).where(
                ConversationMessage.conversation_id == conversation.id
            )
        )
        next_ordinal = maximum + 1 if isinstance(maximum, int) else 1
        user = ConversationMessage(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            class_id=conversation.class_id,
            student_id=conversation.student_id,
            agent_id=conversation.agent_id,
            ordinal=next_ordinal,
            role=ConversationMessageRole.USER.value,
            state=ConversationMessageState.COMPLETED.value,
            content=clean,
            completed_at=datetime.now(UTC),
        )
        assistant = ConversationMessage(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            class_id=conversation.class_id,
            student_id=conversation.student_id,
            agent_id=conversation.agent_id,
            ordinal=next_ordinal + 1,
            role=ConversationMessageRole.ASSISTANT.value,
            state=ConversationMessageState.PROCESSING.value,
            applied_agent_revision_id=agent.published_revision_id,
            configuration_updated=(
                previous_revision is not None and previous_revision != agent.published_revision_id
            ),
        )
        conversation.updated_at = datetime.now(UTC)
        session.add_all([user, assistant])
        session.flush()
        return conversation, user, assistant

    def complete_turn(
        self,
        session: Session,
        assistant: ConversationMessage,
        *,
        answer: str,
        retrieval_mode: str,
        evidence: list[EvidenceItem],
        citation_ids: list[str],
    ) -> None:
        if assistant.state != ConversationMessageState.PROCESSING.value:
            raise ValueError("assistant turn is not processing")
        from campusclaw.application.generation import source_response

        if assistant.role != ConversationMessageRole.ASSISTANT.value:
            raise ValueError("not an assistant turn")
        if (
            not answer
            or len(answer) > 20_000
            or retrieval_mode not in {"keyword", "vector", "hybrid", "keyword_only"}
        ):
            raise ValueError("invalid completion")
        sources = {item.source_id: item for item in evidence}
        if len(sources) != len(evidence) or len(citation_ids) != len(set(citation_ids)):
            raise ValueError("duplicate citation")
        if len(citation_ids) > 100 or any(key not in sources for key in citation_ids):
            raise ValueError("unknown citation")
        cited = [sources[key] for key in citation_ids]
        if any(
            item.material.class_id != assistant.class_id
            or item.chunk.class_id != assistant.class_id
            or item.chunk.material_id != item.material.id
            for item in cited
        ):
            raise ValueError("invalid citation scope")
        snapshots = [CitationSource.model_validate(source_response(item)) for item in cited]
        assistant.state = ConversationMessageState.COMPLETED.value
        assistant.content = answer
        assistant.retrieval_mode = retrieval_mode
        assistant.safe_error_code = None
        assistant.completed_at = datetime.now(UTC)
        for ordinal, (item, snapshot) in enumerate(zip(cited, snapshots, strict=True), start=1):
            locator = (
                f"page {item.chunk.page}"
                if item.chunk.page is not None
                else f"lines {item.chunk.line_start}-{item.chunk.line_end}"
            )
            session.add(
                MessageCitation(
                    id=uuid.uuid4(),
                    message_id=assistant.id,
                    class_id=assistant.class_id,
                    ordinal=ordinal,
                    material_id=item.material.id,
                    chunk_id=item.chunk.id,
                    source_title=item.material.title,
                    locator=locator,
                    source_snapshot=snapshot.model_dump(mode="json"),
                )
            )
        session.flush()

    def fail_turn(self, session: Session, assistant: ConversationMessage, *, code: str) -> None:
        if assistant.state != ConversationMessageState.PROCESSING.value:
            return
        assistant.state = ConversationMessageState.FAILED.value
        assistant.content = None
        assistant.retrieval_mode = None
        assistant.safe_error_code = (
            code
            if code
            in {
                "generation_failed",
                "generation_invalid",
                "answer_generation_unavailable",
                "vector_unavailable",
                "generation_timeout",
                "source_unavailable",
            }
            else "generation_failed"
        )
        assistant.completed_at = datetime.now(UTC)
        session.flush()

    @staticmethod
    def _require_student(principal: Principal) -> None:
        if principal.role is not UserRole.STUDENT:
            raise PermissionError("student role required")

    @staticmethod
    def _require_teacher(principal: Principal) -> None:
        if principal.role is not UserRole.TEACHER:
            raise PermissionError("teacher role required")
