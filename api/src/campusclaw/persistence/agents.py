# pyright: basic, reportMissingImports=false
"""Scoped persistence queries for teacher-managed agents and skills."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from campusclaw.domain.models import Agent, AgentState, Skill, SkillState


class AgentRepository:
    """Read agents only through an authenticated class and creator scope."""

    def list_for_creator(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        creator_id: uuid.UUID,
    ) -> list[Agent]:
        statement = (
            select(Agent)
            .where(Agent.class_id == class_id, Agent.creator_id == creator_id)
            .order_by(Agent.created_at.desc(), Agent.id.desc())
        )
        return list(session.scalars(statement))

    def get_for_creator(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        creator_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> Agent | None:
        statement = select(Agent).where(
            Agent.id == agent_id,
            Agent.class_id == class_id,
            Agent.creator_id == creator_id,
        )
        return session.scalar(statement)

    def list_published_for_class(self, session: Session, *, class_id: uuid.UUID) -> list[Agent]:
        statement = (
            select(Agent)
            .where(Agent.class_id == class_id, Agent.state == AgentState.PUBLISHED.value)
            .order_by(Agent.created_at.desc(), Agent.id.desc())
        )
        return list(session.scalars(statement))

    def get_published_for_class(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> Agent | None:
        statement = select(Agent).where(
            Agent.id == agent_id,
            Agent.class_id == class_id,
            Agent.state == AgentState.PUBLISHED.value,
        )
        return session.scalar(statement)


class SkillRepository:
    """Read skills only through an authenticated class and creator scope."""

    def list_for_creator(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        creator_id: uuid.UUID,
    ) -> list[Skill]:
        statement = (
            select(Skill)
            .where(Skill.class_id == class_id, Skill.creator_id == creator_id)
            .order_by(Skill.created_at.desc(), Skill.id.desc())
        )
        return list(session.scalars(statement))

    def get_for_creator(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        creator_id: uuid.UUID,
        skill_id: uuid.UUID,
    ) -> Skill | None:
        statement = select(Skill).where(
            Skill.id == skill_id,
            Skill.class_id == class_id,
            Skill.creator_id == creator_id,
        )
        return session.scalar(statement)

    def get_active_for_creator(
        self,
        session: Session,
        *,
        class_id: uuid.UUID,
        creator_id: uuid.UUID,
        skill_id: uuid.UUID,
    ) -> Skill | None:
        statement = select(Skill).where(
            Skill.id == skill_id,
            Skill.class_id == class_id,
            Skill.creator_id == creator_id,
            Skill.state == SkillState.ACTIVE.value,
        )
        return session.scalar(statement)
