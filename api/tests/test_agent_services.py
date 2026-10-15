# pyright: basic, reportMissingImports=false
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal
from campusclaw.application.agents import AgentNotReadyError, AgentService, MissingAgentError
from campusclaw.application.skills import SOLUTION_GUIDANCE_POLICY, MissingSkillError, SkillService
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import AgentState, Base, Class, User, UserRole


def setup(tmp_path: Path) -> tuple[Session, Settings, Principal, Principal, Principal]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'services.db'}")
    Base.metadata.create_all(engine)
    class_id, owner_id, peer_id, student_id = (uuid.uuid4() for _ in range(4))
    session = Session(engine)
    session.add(Class(id=class_id, name="A"))
    session.flush()
    for user_id, account, role in (
        (owner_id, "owner", "teacher"),
        (peer_id, "peer", "teacher"),
        (student_id, "student", "student"),
    ):
        session.add(
            User(id=user_id, account=account, password_hash="hash", role=role, class_id=class_id)
        )
    session.commit()
    settings = Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL="postgresql+psycopg://x",
        JWT_SIGNING_KEY=SecretStr("k" * 32),
        UPLOAD_ROOT=tmp_path,
    )
    return (
        session,
        settings,
        Principal(owner_id, "owner", UserRole.TEACHER, class_id),
        Principal(peer_id, "peer", UserRole.TEACHER, class_id),
        Principal(student_id, "student", UserRole.STUDENT, class_id),
    )


def test_creator_owned_skill_and_agent_lifecycle(tmp_path: Path) -> None:
    session, settings, owner, peer, student = setup(tmp_path)
    skills = SkillService(settings)
    agents = AgentService(settings)
    skill = skills.create(
        session, owner, name="Guide", skill_type="solution_guidance", instructions="Use hints."
    )
    agent = agents.create(
        session, owner, name="Tutor", description=None, system_prompt="Guide.", skill_ids=[skill.id]
    )
    agents.publish(session, owner, agent.id)
    assert agent.state == AgentState.PUBLISHED.value
    assert (
        agents.require_published_for_student(session, class_id=owner.class_id, agent_id=agent.id)
        == agent
    )
    assert SOLUTION_GUIDANCE_POLICY in skills.protected_solution_guidance(session, skill)
    skills.retire(session, owner, skill.id)
    assert agent.state == AgentState.DRAFT.value
    with pytest.raises(AgentNotReadyError):
        agents.require_published_for_student(session, class_id=owner.class_id, agent_id=agent.id)
    with pytest.raises(AgentNotReadyError):
        agents.publish(session, owner, agent.id)
    with pytest.raises(PermissionError):
        skills.create(
            session, student, name="No", skill_type="solution_guidance", instructions="No"
        )
    with pytest.raises(MissingAgentError):
        agents.read(session, owner, uuid.uuid4())
    with pytest.raises(MissingSkillError):
        skills.read(session, owner, uuid.uuid4())
    with pytest.raises(MissingSkillError):
        skills.read(session, peer, skill.id)
    with pytest.raises(MissingAgentError):
        agents.read(session, peer, agent.id)
    session.close()


def test_duplicate_or_inaccessible_skill_binding_creates_no_agent(tmp_path: Path) -> None:
    session, settings, owner, _, _ = setup(tmp_path)
    skills = SkillService(settings)
    agents = AgentService(settings)
    skill = skills.create(
        session, owner, name="Guide", skill_type="solution_guidance", instructions="Use hints."
    )
    with pytest.raises(ValueError):
        agents.create(
            session,
            owner,
            name="Tutor",
            description=None,
            system_prompt="Guide.",
            skill_ids=[skill.id, skill.id],
        )
    with pytest.raises(MissingAgentError):
        agents.create(
            session,
            owner,
            name="Tutor",
            description=None,
            system_prompt="Guide.",
            skill_ids=[uuid.uuid4()],
        )
    assert agents.list_for_creator(session, owner) == []
    second = skills.create(
        session, owner, name="Guide 2", skill_type="solution_guidance", instructions="Use checks."
    )
    first_agent = agents.create(
        session,
        owner,
        name="Tutor 1",
        description=None,
        system_prompt="Guide.",
        skill_ids=[skill.id],
    )
    second_agent = agents.create(
        session,
        owner,
        name="Tutor 2",
        description="More",
        system_prompt="Guide.",
        skill_ids=[second.id],
    )
    assert {agent.id for agent in agents.list_for_creator(session, owner)} == {
        first_agent.id,
        second_agent.id,
    }
    with pytest.raises(ValueError):
        agents.update(
            session,
            owner,
            first_agent.id,
            name="",
            description=None,
            system_prompt="Guide.",
            skill_ids=[skill.id],
        )
    session.close()
