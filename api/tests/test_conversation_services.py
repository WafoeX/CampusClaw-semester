import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from campusclaw.api.dependencies import Principal
from campusclaw.application.agents import AgentService
from campusclaw.application.conversations import (
    ConversationService,
    MissingConversationError,
    TurnInProgressError,
)
from campusclaw.application.skills import SkillService
from campusclaw.config import AppEnvironment, Settings
from campusclaw.domain.models import (
    Base,
    Class,
    ConversationMessageState,
    User,
    UserRole,
)


def setup(tmp_path: Path) -> tuple[Session, Settings, Principal, Principal, Principal, uuid.UUID]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'conversations.db'}")
    Base.metadata.create_all(engine)
    class_id, other_class, teacher_id, student_id, peer_id = (uuid.uuid4() for _ in range(5))
    session = Session(engine)
    session.add_all([Class(id=class_id, name="A"), Class(id=other_class, name="B")])
    session.add_all(
        [
            User(
                id=teacher_id,
                account="teacher",
                password_hash="hash",
                role="teacher",
                class_id=class_id,
            ),
            User(
                id=student_id,
                account="student",
                password_hash="hash",
                role="student",
                class_id=class_id,
            ),
            User(
                id=peer_id, account="peer", password_hash="hash", role="student", class_id=class_id
            ),
        ]
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
        Principal(teacher_id, "teacher", UserRole.TEACHER, class_id),
        Principal(student_id, "student", UserRole.STUDENT, class_id),
        Principal(peer_id, "peer", UserRole.STUDENT, class_id),
        other_class,
    )


def published_agent(session: Session, settings: Settings, teacher: Principal) -> uuid.UUID:
    skill = SkillService(settings).create(
        session,
        teacher,
        name="Guide",
        skill_type="solution_guidance",
        instructions="Use hints.",
    )
    agent = AgentService(settings).create(
        session,
        teacher,
        name="Tutor",
        description=None,
        system_prompt="Use evidence.",
        skill_ids=[skill.id],
    )
    AgentService(settings).publish(session, teacher, agent.id)
    session.commit()
    return agent.id


def test_student_conversation_is_scoped_ordered_and_soft_deleted(tmp_path: Path) -> None:
    session, settings, teacher, student, peer, _ = setup(tmp_path)
    agent_id = published_agent(session, settings, teacher)
    service = ConversationService(settings)
    conversation = service.create(session, student, agent_id=agent_id)
    session.commit()
    assert [item.id for item in service.list_for_student(session, student)] == [conversation.id]
    with pytest.raises(MissingConversationError):
        service.read_for_student(session, peer, conversation.id)

    _, user, assistant = service.accept_turn(
        session, student, conversation.id, content="How does this work?"
    )
    assert (user.ordinal, assistant.ordinal) == (1, 2)
    assert assistant.state == ConversationMessageState.PROCESSING.value
    with pytest.raises(TurnInProgressError):
        service.accept_turn(session, student, conversation.id, content="second")
    service.fail_turn(session, assistant, code="generation_failed")
    session.commit()
    assert service.history(session, conversation) == [user]

    service.soft_delete(session, student, conversation.id)
    session.commit()
    assert service.list_for_student(session, student) == []
    with pytest.raises(MissingConversationError):
        service.accept_turn(session, student, conversation.id, content="blocked")
    audit = service.list_for_creator(session, teacher, agent_id)
    assert audit == [conversation]
    session.close()
