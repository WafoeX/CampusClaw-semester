# pyright: basic, reportMissingImports=false
"""Creator-owned skill lifecycle and protected solution-guidance policy."""

import builtins
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal
from campusclaw.application.agent_revisions import (
    create_skill_revision,
    latest_skill_revision,
    propagate_skill_revision,
)
from campusclaw.application.tool_bindings import reference_list, resolve_bindings
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
from campusclaw.persistence.agents import SkillRepository

SOLUTION_GUIDANCE_POLICY = (
    "Provide hints, intermediate steps, checks, or clarifying questions; "
    "do not directly provide the requested final answer."
)


class MissingSkillError(LookupError):
    """Existence-hiding error for inaccessible skill identifiers."""


class SkillService:
    def __init__(self, settings: Settings, repository: SkillRepository | None = None) -> None:
        self._settings = settings
        self._repository = repository or SkillRepository()

    def create(
        self,
        session: Session,
        principal: Principal,
        *,
        name: str,
        skill_type: str,
        instructions: str,
        tools: list[str] | None = None,
    ) -> Skill:
        self._require_teacher(principal)
        self._validate(name, skill_type, instructions)
        bindings = resolve_bindings(
            session, principal.class_id, tools if tools is not None else ["knowledge_search"]
        )
        skill = Skill(
            id=uuid.uuid4(),
            class_id=principal.class_id,
            creator_id=principal.user_id,
            state=SkillState.ACTIVE.value,
        )
        session.add(skill)
        session.flush()
        create_skill_revision(
            session,
            skill,
            name=name.strip(),
            skill_type=skill_type,
            instructions=instructions.strip(),
            tools=bindings,
        )
        return skill

    def read(self, session: Session, principal: Principal, skill_id: uuid.UUID) -> Skill:
        self._require_teacher(principal)
        skill = self._repository.get_for_creator(
            session,
            class_id=principal.class_id,
            creator_id=principal.user_id,
            skill_id=skill_id,
        )
        if skill is None:
            raise MissingSkillError()
        return skill

    def list(self, session: Session, principal: Principal) -> list[Skill]:
        self._require_teacher(principal)
        return self._repository.list_for_creator(
            session, class_id=principal.class_id, creator_id=principal.user_id
        )

    def update(
        self,
        session: Session,
        principal: Principal,
        skill_id: uuid.UUID,
        *,
        name: str,
        skill_type: str,
        instructions: str,
        tools: builtins.list[str] | None = None,
    ) -> Skill:
        skill = self.read(session, principal, skill_id)
        if skill.state != SkillState.ACTIVE.value:
            raise MissingSkillError()
        self._validate(name, skill_type, instructions)
        previous = latest_skill_revision(session, skill)
        if previous is None:
            raise RuntimeError("active skill has no revision")
        bindings = resolve_bindings(
            session,
            principal.class_id,
            reference_list(previous.tools) if tools is None else tools,
            previous=previous.tools,
        )
        replacement = create_skill_revision(
            session,
            skill,
            name=name.strip(),
            skill_type=skill_type,
            instructions=instructions.strip(),
            tools=bindings,
        )
        propagate_skill_revision(session, previous, replacement)
        return skill

    def retire(self, session: Session, principal: Principal, skill_id: uuid.UUID) -> Skill:
        skill = self.read(session, principal, skill_id)
        skill.state = SkillState.RETIRED.value
        affected_agents = session.scalars(
            select(Agent)
            .join(AgentRevision, Agent.current_revision_id == AgentRevision.id)
            .join(AgentSkillBinding, AgentSkillBinding.agent_revision_id == AgentRevision.id)
            .join(SkillRevision, AgentSkillBinding.skill_revision_id == SkillRevision.id)
            .where(SkillRevision.skill_id == skill.id)
        )
        for agent in affected_agents:
            if agent.state == AgentState.PUBLISHED.value:
                agent.state = AgentState.DRAFT.value
                agent.published_revision_id = None
        return skill

    def protected_solution_guidance(self, session: Session, skill: Skill) -> str:
        revision = latest_skill_revision(session, skill)
        if revision is None:
            raise RuntimeError("active skill has no revision")
        return (
            f"{SOLUTION_GUIDANCE_POLICY}\n\n"
            f"Untrusted teacher configuration:\n{revision.instructions}"
        )

    def _require_teacher(self, principal: Principal) -> None:
        if principal.role is not UserRole.TEACHER:
            raise PermissionError("teacher role required")

    def _validate(self, name: str, skill_type: str, instructions: str) -> None:
        if not name.strip() or len(name.strip()) > self._settings.SKILL_NAME_MAX_CHARS:
            raise ValueError("invalid skill name")
        if skill_type != SkillType.SOLUTION_GUIDANCE.value:
            raise ValueError("unsupported skill type")
        if (
            not instructions.strip()
            or len(instructions.strip()) > self._settings.SKILL_INSTRUCTIONS_MAX_CHARS
        ):
            raise ValueError("invalid skill instructions")
