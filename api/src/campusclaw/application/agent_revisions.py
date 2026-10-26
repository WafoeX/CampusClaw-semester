# pyright: basic, reportMissingImports=false
"""Immutable agent and skill configuration revisions."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from campusclaw.application.tool_bindings import ensure_tool_union
from campusclaw.domain.models import (
    Agent,
    AgentRevision,
    AgentSkillBinding,
    AgentState,
    Skill,
    SkillRevision,
)


def _next_agent_revision_number(session: Session, agent_id: uuid.UUID) -> int:
    maximum = session.scalar(
        select(func.max(AgentRevision.revision_number)).where(AgentRevision.agent_id == agent_id)
    )
    return (maximum or 0) + 1


def _next_skill_revision_number(session: Session, skill_id: uuid.UUID) -> int:
    maximum = session.scalar(
        select(func.max(SkillRevision.revision_number)).where(SkillRevision.skill_id == skill_id)
    )
    return (maximum or 0) + 1


def create_agent_revision(
    session: Session,
    agent: Agent,
    *,
    name: str,
    description: str | None,
    system_prompt: str,
) -> AgentRevision:
    revision = AgentRevision(
        agent_id=agent.id,
        class_id=agent.class_id,
        creator_id=agent.creator_id,
        revision_number=_next_agent_revision_number(session, agent.id),
        name=name,
        description=description,
        system_prompt=system_prompt,
    )
    session.add(revision)
    session.flush()
    agent.current_revision_id = revision.id
    return revision


def create_skill_revision(
    session: Session,
    skill: Skill,
    *,
    name: str,
    skill_type: str,
    instructions: str,
    tools: list[Any] | None = None,
) -> SkillRevision:
    revision = SkillRevision(
        skill_id=skill.id,
        class_id=skill.class_id,
        creator_id=skill.creator_id,
        revision_number=_next_skill_revision_number(session, skill.id),
        name=name,
        skill_type=skill_type,
        instructions=instructions,
        tools=tools if tools is not None else ["knowledge_search"],
    )
    session.add(revision)
    session.flush()
    skill.current_revision_id = revision.id
    return revision


def latest_agent_revision(session: Session, agent: Agent) -> AgentRevision | None:
    return session.scalar(
        select(AgentRevision)
        .where(AgentRevision.agent_id == agent.id)
        .order_by(AgentRevision.revision_number.desc())
    )


def latest_skill_revision(session: Session, skill: Skill) -> SkillRevision | None:
    return session.scalar(
        select(SkillRevision)
        .where(SkillRevision.skill_id == skill.id)
        .order_by(SkillRevision.revision_number.desc())
    )


def propagate_skill_revision(
    session: Session, previous: SkillRevision, replacement: SkillRevision
) -> list[AgentRevision]:
    """Clone current agent configurations that bind ``previous`` to ``replacement``."""
    statement = (
        select(Agent)
        .join(AgentRevision, Agent.current_revision_id == AgentRevision.id)
        .join(AgentSkillBinding, AgentSkillBinding.agent_revision_id == AgentRevision.id)
        .where(AgentSkillBinding.skill_revision_id == previous.id)
    )
    agents = list(session.scalars(statement))
    replacements: list[AgentRevision] = []
    for agent in agents:
        current = latest_agent_revision(session, agent)
        if current is None:
            continue
        bound = list(
            session.scalars(
                select(SkillRevision)
                .join(AgentSkillBinding, AgentSkillBinding.skill_revision_id == SkillRevision.id)
                .where(AgentSkillBinding.agent_revision_id == current.id)
            )
        )
        ensure_tool_union([replacement if item.id == previous.id else item for item in bound])
        copied = create_agent_revision(
            session,
            agent,
            name=current.name,
            description=current.description,
            system_prompt=current.system_prompt,
        )
        bindings = list(
            session.scalars(
                select(AgentSkillBinding).where(AgentSkillBinding.agent_revision_id == current.id)
            )
        )
        for binding in bindings:
            session.add(
                AgentSkillBinding(
                    agent_revision_id=copied.id,
                    skill_revision_id=(
                        replacement.id
                        if binding.skill_revision_id == previous.id
                        else binding.skill_revision_id
                    ),
                    class_id=agent.class_id,
                    creator_id=agent.creator_id,
                )
            )
        if agent.state == AgentState.PUBLISHED.value:
            agent.state = AgentState.DRAFT.value
            agent.published_revision_id = None
        replacements.append(copied)
    session.flush()
    return replacements
