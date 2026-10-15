# pyright: basic, reportMissingImports=false
"""Creator-owned agent configuration and publication lifecycle."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal
from campusclaw.application.agent_revisions import create_agent_revision, latest_agent_revision
from campusclaw.config import Settings
from campusclaw.domain.models import (
    Agent,
    AgentRevision,
    AgentSkillBinding,
    AgentState,
    Skill,
    SkillRevision,
    SkillState,
    SkillType,
    UserRole,
)
from campusclaw.persistence.agents import AgentRepository, SkillRepository


class MissingAgentError(LookupError):
    """Existence-hiding error for inaccessible agent identifiers."""


class AgentNotReadyError(ValueError):
    """A draft cannot become student-visible until all required inputs exist."""


class AgentService:
    def __init__(
        self,
        settings: Settings,
        agent_repository: AgentRepository | None = None,
        skill_repository: SkillRepository | None = None,
    ) -> None:
        self._settings = settings
        self._agents = agent_repository or AgentRepository()
        self._skills = skill_repository or SkillRepository()

    def create(
        self,
        session: Session,
        principal: Principal,
        *,
        name: str,
        description: str | None,
        system_prompt: str,
        skill_ids: list[uuid.UUID],
    ) -> Agent:
        self._require_teacher(principal)
        self._validate(name, description, system_prompt)
        skills = self._bound_skills(session, principal, skill_ids)
        agent = Agent(id=uuid.uuid4(), class_id=principal.class_id, creator_id=principal.user_id)
        session.add(agent)
        session.flush()
        revision = create_agent_revision(
            session,
            agent,
            name=name.strip(),
            description=description.strip() if description else None,
            system_prompt=system_prompt.strip(),
        )
        self._bind(session, agent, revision, skills)
        return agent

    def read(self, session: Session, principal: Principal, agent_id: uuid.UUID) -> Agent:
        if principal.role is not UserRole.TEACHER:
            raise MissingAgentError()
        agent = self._agents.get_for_creator(
            session,
            class_id=principal.class_id,
            creator_id=principal.user_id,
            agent_id=agent_id,
        )
        if agent is None:
            raise MissingAgentError()
        return agent

    def list_for_creator(self, session: Session, principal: Principal) -> list[Agent]:
        self._require_teacher(principal)
        return self._agents.list_for_creator(
            session, class_id=principal.class_id, creator_id=principal.user_id
        )

    def update(
        self,
        session: Session,
        principal: Principal,
        agent_id: uuid.UUID,
        *,
        name: str,
        description: str | None,
        system_prompt: str,
        skill_ids: list[uuid.UUID],
    ) -> Agent:
        agent = self.read(session, principal, agent_id)
        if agent.state == AgentState.RETIRED.value:
            raise MissingAgentError()
        self._validate(name, description, system_prompt)
        skills = self._bound_skills(session, principal, skill_ids)
        revision = create_agent_revision(
            session,
            agent,
            name=name.strip(),
            description=description.strip() if description else None,
            system_prompt=system_prompt.strip(),
        )
        self._bind(session, agent, revision, skills)
        agent.state = AgentState.DRAFT.value
        agent.published_revision_id = None
        return agent

    def retire(self, session: Session, principal: Principal, agent_id: uuid.UUID) -> Agent:
        agent = self.read(session, principal, agent_id)
        agent.state = AgentState.RETIRED.value
        agent.published_revision_id = None
        return agent

    def publish(self, session: Session, principal: Principal, agent_id: uuid.UUID) -> Agent:
        agent = self.read(session, principal, agent_id)
        if agent.state == AgentState.RETIRED.value:
            raise AgentNotReadyError("retired agent cannot be published")
        revision = latest_agent_revision(session, agent)
        if revision is None or not revision.system_prompt.strip():
            raise AgentNotReadyError("agent requires a prompt")
        has_guidance = session.scalar(
            select(AgentSkillBinding.id)
            .join(SkillRevision, AgentSkillBinding.skill_revision_id == SkillRevision.id)
            .join(Skill, SkillRevision.skill_id == Skill.id)
            .where(
                AgentSkillBinding.agent_revision_id == revision.id,
                SkillRevision.skill_type == SkillType.SOLUTION_GUIDANCE.value,
                Skill.state == SkillState.ACTIVE.value,
            )
            .limit(1)
        )
        if has_guidance is None:
            raise AgentNotReadyError("agent requires an active solution-guidance skill")
        agent.state = AgentState.PUBLISHED.value
        agent.published_revision_id = revision.id
        return agent

    def unpublish(self, session: Session, principal: Principal, agent_id: uuid.UUID) -> Agent:
        agent = self.read(session, principal, agent_id)
        if agent.state != AgentState.RETIRED.value:
            agent.state = AgentState.DRAFT.value
        agent.published_revision_id = None
        return agent

    def require_published_for_student(
        self, session: Session, *, class_id: uuid.UUID, agent_id: uuid.UUID
    ) -> Agent:
        """Return only an agent that may accept a new student conversation turn."""
        agent = self._agents.get_published_for_class(session, class_id=class_id, agent_id=agent_id)
        if agent is None or agent.published_revision_id is None:
            raise AgentNotReadyError("agent is not available for student conversations")
        return agent

    def _bound_skills(
        self, session: Session, principal: Principal, skill_ids: list[uuid.UUID]
    ) -> list[SkillRevision]:
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("duplicate skill identifiers")
        revisions: list[SkillRevision] = []
        for skill_id in skill_ids:
            skill = self._skills.get_active_for_creator(
                session,
                class_id=principal.class_id,
                creator_id=principal.user_id,
                skill_id=skill_id,
            )
            if skill is None:
                raise MissingAgentError()
            revision = self._latest_skill_revision(session, skill_id)
            if revision is None:
                raise MissingAgentError()
            revisions.append(revision)
        return revisions

    def _bind(
        self,
        session: Session,
        agent: Agent,
        revision: AgentRevision,
        skills: list[SkillRevision],
    ) -> None:
        for skill in skills:
            session.add(
                AgentSkillBinding(
                    agent_revision_id=revision.id,
                    skill_revision_id=skill.id,
                    class_id=agent.class_id,
                    creator_id=agent.creator_id,
                )
            )
        session.flush()

    def _latest_skill_revision(self, session: Session, skill_id: uuid.UUID) -> SkillRevision | None:
        return session.scalar(
            select(SkillRevision)
            .where(SkillRevision.skill_id == skill_id)
            .order_by(SkillRevision.revision_number.desc())
        )

    def _require_teacher(self, principal: Principal) -> None:
        if principal.role is not UserRole.TEACHER:
            raise PermissionError("teacher role required")

    def _validate(self, name: str, description: str | None, system_prompt: str) -> None:
        if not name.strip() or len(name.strip()) > self._settings.AGENT_NAME_MAX_CHARS:
            raise ValueError("invalid agent name")
        if (
            description is not None
            and len(description.strip()) > self._settings.AGENT_DESCRIPTION_MAX_CHARS
        ):
            raise ValueError("invalid agent description")
        if (
            not system_prompt.strip()
            or len(system_prompt.strip()) > self._settings.AGENT_PROMPT_MAX_CHARS
        ):
            raise ValueError("invalid agent prompt")
