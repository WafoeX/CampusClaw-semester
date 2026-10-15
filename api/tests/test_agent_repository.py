# pyright: basic, reportMissingImports=false
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from campusclaw.domain.models import Agent, AgentState, Base, Class, Skill, User
from campusclaw.persistence.agents import AgentRepository, SkillRepository


def scoped_session(tmp_path: Path) -> tuple[Session, dict[str, uuid.UUID]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'agents.db'}")
    Base.metadata.create_all(engine)
    ids = {name: uuid.uuid4() for name in ("alpha", "beta", "owner", "peer", "other")}
    with Session(engine) as session:
        session.add_all(
            [
                Class(id=ids["alpha"], name="Alpha"),
                Class(id=ids["beta"], name="Beta"),
            ]
        )
        session.flush()
        session.add_all(
            [
                User(
                    id=ids["owner"],
                    account="owner",
                    password_hash="hash",
                    role="teacher",
                    class_id=ids["alpha"],
                ),
                User(
                    id=ids["peer"],
                    account="peer",
                    password_hash="hash",
                    role="teacher",
                    class_id=ids["alpha"],
                ),
                User(
                    id=ids["other"],
                    account="other",
                    password_hash="hash",
                    role="teacher",
                    class_id=ids["beta"],
                ),
            ]
        )
        session.flush()
        ids |= {name: uuid.uuid4() for name in ("owned_agent", "peer_agent", "other_agent")}
        session.add_all(
            [
                Agent(
                    id=ids["owned_agent"],
                    class_id=ids["alpha"],
                    creator_id=ids["owner"],
                    state=AgentState.PUBLISHED.value,
                ),
                Agent(
                    id=ids["peer_agent"],
                    class_id=ids["alpha"],
                    creator_id=ids["peer"],
                    state=AgentState.DRAFT.value,
                ),
                Agent(
                    id=ids["other_agent"],
                    class_id=ids["beta"],
                    creator_id=ids["other"],
                    state=AgentState.PUBLISHED.value,
                ),
            ]
        )
        ids |= {name: uuid.uuid4() for name in ("owned_skill", "peer_skill", "other_skill")}
        session.add_all(
            [
                Skill(id=ids["owned_skill"], class_id=ids["alpha"], creator_id=ids["owner"]),
                Skill(id=ids["peer_skill"], class_id=ids["alpha"], creator_id=ids["peer"]),
                Skill(id=ids["other_skill"], class_id=ids["beta"], creator_id=ids["other"]),
            ]
        )
        session.commit()
    return Session(engine), ids


def test_creator_repositories_hide_other_creators_classes_and_missing_ids(tmp_path: Path) -> None:
    session, ids = scoped_session(tmp_path)
    agents = AgentRepository()
    skills = SkillRepository()
    missing = uuid.uuid4()

    assert [
        agent.id
        for agent in agents.list_for_creator(
            session, class_id=ids["alpha"], creator_id=ids["owner"]
        )
    ] == [ids["owned_agent"]]
    assert (
        agents.get_for_creator(
            session, class_id=ids["alpha"], creator_id=ids["owner"], agent_id=ids["owned_agent"]
        )
        is not None
    )
    assert (
        agents.get_for_creator(
            session, class_id=ids["alpha"], creator_id=ids["owner"], agent_id=ids["peer_agent"]
        )
        is None
    )
    assert (
        agents.get_for_creator(
            session, class_id=ids["alpha"], creator_id=ids["owner"], agent_id=ids["other_agent"]
        )
        is None
    )
    assert (
        agents.get_for_creator(
            session, class_id=ids["alpha"], creator_id=ids["owner"], agent_id=missing
        )
        is None
    )

    assert (
        skills.get_for_creator(
            session, class_id=ids["alpha"], creator_id=ids["owner"], skill_id=ids["owned_skill"]
        )
        is not None
    )
    assert (
        skills.get_for_creator(
            session, class_id=ids["alpha"], creator_id=ids["owner"], skill_id=ids["peer_skill"]
        )
        is None
    )
    assert (
        skills.get_for_creator(
            session, class_id=ids["alpha"], creator_id=ids["owner"], skill_id=ids["other_skill"]
        )
        is None
    )
    assert (
        skills.get_for_creator(
            session, class_id=ids["alpha"], creator_id=ids["owner"], skill_id=missing
        )
        is None
    )
    session.close()


def test_student_catalog_repository_selects_only_same_class_published_agents(
    tmp_path: Path,
) -> None:
    session, ids = scoped_session(tmp_path)
    agents = AgentRepository()

    assert [
        agent.id for agent in agents.list_published_for_class(session, class_id=ids["alpha"])
    ] == [ids["owned_agent"]]
    assert (
        agents.get_published_for_class(session, class_id=ids["alpha"], agent_id=ids["owned_agent"])
        is not None
    )
    assert (
        agents.get_published_for_class(session, class_id=ids["alpha"], agent_id=ids["peer_agent"])
        is None
    )
    assert (
        agents.get_published_for_class(session, class_id=ids["alpha"], agent_id=ids["other_agent"])
        is None
    )
    session.close()
