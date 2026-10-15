# pyright: basic, reportMissingImports=false
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from campusclaw.application.agent_revisions import (
    create_agent_revision,
    create_skill_revision,
    latest_agent_revision,
    latest_skill_revision,
    propagate_skill_revision,
)
from campusclaw.domain.models import (
    Agent,
    AgentSkillBinding,
    AgentState,
    Base,
    Class,
    Skill,
    User,
)


def revision_session(tmp_path: Path) -> tuple[Session, Agent, Skill]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'revisions.db'}")
    Base.metadata.create_all(engine)
    class_id, teacher_id = uuid.uuid4(), uuid.uuid4()
    agent = Agent(id=uuid.uuid4(), class_id=class_id, creator_id=teacher_id)
    skill = Skill(id=uuid.uuid4(), class_id=class_id, creator_id=teacher_id)
    session = Session(engine)
    session.add(Class(id=class_id, name="Revision class"))
    session.flush()
    session.add(
        User(
            id=teacher_id,
            account="teacher.revision",
            password_hash="hash",
            role="teacher",
            class_id=class_id,
        )
    )
    session.flush()
    session.add_all([agent, skill])
    session.flush()
    return session, agent, skill


def test_revisions_are_immutable_and_latest_selection_is_deterministic(tmp_path: Path) -> None:
    session, agent, skill = revision_session(tmp_path)
    first_agent = create_agent_revision(
        session, agent, name="Tutor", description="First", system_prompt="Guide."
    )
    second_agent = create_agent_revision(
        session, agent, name="Tutor", description="Second", system_prompt="Guide more."
    )
    first_skill = create_skill_revision(
        session,
        skill,
        name="Guidance",
        skill_type="solution_guidance",
        instructions="Offer hints.",
    )
    second_skill = create_skill_revision(
        session,
        skill,
        name="Guidance",
        skill_type="solution_guidance",
        instructions="Offer checks.",
    )
    session.commit()

    assert first_agent.revision_number == first_skill.revision_number == 1
    assert first_agent.description == "First"
    assert first_skill.instructions == "Offer hints."
    assert latest_agent_revision(session, agent) == second_agent
    assert latest_skill_revision(session, skill) == second_skill
    assert agent.current_revision_id == second_agent.id
    assert skill.current_revision_id == second_skill.id
    session.close()


def test_skill_revision_propagation_clones_current_agent_revision(tmp_path: Path) -> None:
    session, agent, skill = revision_session(tmp_path)
    old_skill = create_skill_revision(
        session,
        skill,
        name="Guidance",
        skill_type="solution_guidance",
        instructions="Offer hints.",
    )
    current_agent = create_agent_revision(
        session, agent, name="Tutor", description=None, system_prompt="Guide."
    )
    session.add(
        AgentSkillBinding(
            agent_revision_id=current_agent.id,
            skill_revision_id=old_skill.id,
            class_id=agent.class_id,
            creator_id=agent.creator_id,
        )
    )
    agent.state = AgentState.PUBLISHED.value
    agent.published_revision_id = current_agent.id
    session.flush()
    replacement_skill = create_skill_revision(
        session,
        skill,
        name="Guidance",
        skill_type="solution_guidance",
        instructions="Offer checks.",
    )

    replacements = propagate_skill_revision(session, old_skill, replacement_skill)
    session.commit()

    assert len(replacements) == 1
    replacement_agent = replacements[0]
    assert replacement_agent.revision_number == current_agent.revision_number + 1
    assert replacement_agent.system_prompt == current_agent.system_prompt
    assert agent.current_revision_id == replacement_agent.id
    assert agent.state == AgentState.DRAFT.value
    assert agent.published_revision_id is None
    bindings = list(
        session.scalars(
            select(AgentSkillBinding).where(
                AgentSkillBinding.agent_revision_id == replacement_agent.id
            )
        )
    )
    assert [binding.skill_revision_id for binding in bindings] == [replacement_skill.id]
    session.close()
