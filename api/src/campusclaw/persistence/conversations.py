"""Class- and owner-scoped conversation persistence queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from campusclaw.domain.models import (
    Agent,
    Conversation,
    ConversationMessage,
    ConversationMessageState,
    MessageCitation,
)


class ConversationRepository:
    def list_for_student(
        self, session: Session, *, class_id: uuid.UUID, student_id: uuid.UUID
    ) -> list[Conversation]:
        statement = (
            select(Conversation)
            .where(
                Conversation.class_id == class_id,
                Conversation.student_id == student_id,
                Conversation.deleted_at.is_(None),
            )
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        )
        return list(session.scalars(statement))

    def get_for_student(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        student_id: uuid.UUID,
        conversation_id: uuid.UUID,
        active_only: bool = True,
        lock: bool = False,
    ) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.class_id == class_id,
            Conversation.student_id == student_id,
        )
        if active_only:
            statement = statement.where(Conversation.deleted_at.is_(None))
        if lock:
            statement = statement.with_for_update()
        return session.scalar(statement)

    def list_for_agent_creator(
        self,
        session: Session,
        *,
        agent_id: uuid.UUID,
        creator_id: uuid.UUID,
        class_id: uuid.UUID,
        deleted: bool | None = None,
    ) -> list[Conversation]:
        statement = (
            select(Conversation)
            .join(Agent, Conversation.agent_id == Agent.id)
            .where(
                Conversation.agent_id == agent_id,
                Conversation.class_id == class_id,
                Agent.creator_id == creator_id,
                Agent.class_id == class_id,
            )
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        )
        if deleted is not None:
            statement = statement.where(
                Conversation.deleted_at.is_not(None)
                if deleted
                else Conversation.deleted_at.is_(None)
            )
        return list(session.scalars(statement))

    def get_for_creator(
        self,
        session: Session,
        *,
        conversation_id: uuid.UUID,
        creator_id: uuid.UUID,
        class_id: uuid.UUID,
    ) -> Conversation | None:
        return session.scalar(
            select(Conversation)
            .join(Agent, Conversation.agent_id == Agent.id)
            .where(
                Conversation.id == conversation_id,
                Conversation.class_id == class_id,
                Agent.class_id == class_id,
                Agent.creator_id == creator_id,
            )
        )

    def get_for_agent_creator(
        self,
        session: Session,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        creator_id: uuid.UUID,
        class_id: uuid.UUID,
    ) -> Conversation | None:
        return session.scalar(
            select(Conversation)
            .join(Agent, Conversation.agent_id == Agent.id)
            .where(
                Conversation.id == conversation_id,
                Conversation.agent_id == agent_id,
                Conversation.class_id == class_id,
                Agent.creator_id == creator_id,
                Agent.class_id == class_id,
            )
        )

    def messages(
        self,
        session: Session,
        *,
        conversation: Conversation,
        after_ordinal: int = 0,
        limit: int | None = None,
    ) -> list[ConversationMessage]:
        statement = (
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.class_id == conversation.class_id,
                ConversationMessage.student_id == conversation.student_id,
                ConversationMessage.agent_id == conversation.agent_id,
                ConversationMessage.ordinal > after_ordinal,
            )
            .order_by(ConversationMessage.ordinal)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(session.scalars(statement))

    def history(
        self, session: Session, *, conversation: Conversation, before_ordinal: int, limit: int
    ) -> list[ConversationMessage]:
        """Fetch at most the recent completed suffix, never the just-accepted question."""
        return list(
            session.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == conversation.id,
                    ConversationMessage.class_id == conversation.class_id,
                    ConversationMessage.student_id == conversation.student_id,
                    ConversationMessage.agent_id == conversation.agent_id,
                    ConversationMessage.ordinal < before_ordinal,
                    ConversationMessage.state == ConversationMessageState.COMPLETED.value,
                    ConversationMessage.content.is_not(None),
                )
                .order_by(ConversationMessage.ordinal.desc())
                .limit(limit)
            )
        )

    def citations(self, session: Session, *, message: ConversationMessage) -> list[MessageCitation]:
        return list(
            session.scalars(
                select(MessageCitation)
                .where(
                    MessageCitation.message_id == message.id,
                    MessageCitation.class_id == message.class_id,
                )
                .order_by(MessageCitation.ordinal)
            )
        )

    def has_processing_turn(self, session: Session, *, conversation_id: uuid.UUID) -> bool:
        return (
            session.scalar(
                select(ConversationMessage.id)
                .where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationMessage.state == ConversationMessageState.PROCESSING.value,
                )
                .limit(1)
            )
            is not None
        )
