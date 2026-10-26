# pyright: basic, reportMissingImports=false
import uuid

import pytest
from sqlalchemy import (
    CheckConstraint,
    Constraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from campusclaw.domain.models import (
    Agent,
    AgentRevision,
    AgentSkillBinding,
    Base,
    Class,
    Conversation,
    ConversationMessage,
    Skill,
    SkillRevision,
    User,
)


def constraint_names(table_name: str, kind: type[Constraint]) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {
        str(constraint.name) for constraint in table.constraints if isinstance(constraint, kind)
    }


def test_complete_model_metadata() -> None:
    assert set(Base.metadata.tables) == {
        "classes",
        "users",
        "materials",
        "material_search_states",
        "material_index_versions",
        "knowledge_chunks",
        "material_index_jobs",
        "agents",
        "agent_revisions",
        "skills",
        "skill_revisions",
        "agent_skill_bindings",
        "conversations",
        "conversation_messages",
        "message_citations",
        "mcp_servers",
        "mcp_discovered_tools",
        "mcp_tool_calls",
    }


def test_user_membership_role_and_uniqueness_constraints() -> None:
    users = Base.metadata.tables["users"]
    assert users.c.class_id.nullable is False
    assert users.c.class_id.foreign_keys.pop().target_fullname == "classes.id"
    assert "ck_users_role_supported" in constraint_names("users", CheckConstraint)
    assert "uq_users_account" in constraint_names("users", UniqueConstraint)


def test_knowledge_chunks_use_authoritative_text_without_vectors() -> None:
    chunks = Base.metadata.tables["knowledge_chunks"]
    assert "text" in chunks.c
    assert "normalized_text" in chunks.c
    assert "vector" not in chunks.c
    assert "point_id" not in chunks.c
    assert any(index.name == "ix_knowledge_chunks_normalized_text_trgm" for index in chunks.indexes)


def test_agent_skill_revisions_enforce_creator_scope_and_unique_bindings() -> None:
    agent_revisions = Base.metadata.tables["agent_revisions"]
    skill_revisions = Base.metadata.tables["skill_revisions"]
    bindings = Base.metadata.tables["agent_skill_bindings"]

    assert {
        ("agent_id", "revision_number"),
        ("id", "class_id", "creator_id"),
    } <= {
        tuple(column.name for column in constraint.columns)
        for constraint in agent_revisions.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert {
        ("skill_id", "revision_number"),
        ("id", "class_id", "creator_id"),
    } <= {
        tuple(column.name for column in constraint.columns)
        for constraint in skill_revisions.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("agent_revision_id", "skill_revision_id") in {
        tuple(column.name for column in constraint.columns)
        for constraint in bindings.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    binding_targets = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in bindings.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert (
        "agent_revisions.id",
        "agent_revisions.class_id",
        "agent_revisions.creator_id",
    ) in binding_targets
    assert (
        "skill_revisions.id",
        "skill_revisions.class_id",
        "skill_revisions.creator_id",
    ) in binding_targets


def test_agent_skill_binding_rejects_duplicate_and_cross_creator_rows() -> None:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys = ON")  # type: ignore[attr-defined]

    Base.metadata.create_all(engine)
    class_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    other_creator_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    agent_revision_id = uuid.uuid4()
    skill_id = uuid.uuid4()
    skill_revision_id = uuid.uuid4()
    other_skill_id = uuid.uuid4()
    other_skill_revision_id = uuid.uuid4()

    with Session(engine) as session:
        session.add(Class(id=class_id, name="A"))
        session.flush()
        session.add_all(
            [
                User(
                    id=creator_id,
                    account="creator",
                    password_hash="hash",
                    role="teacher",
                    class_id=class_id,
                ),
                User(
                    id=other_creator_id,
                    account="other",
                    password_hash="hash",
                    role="teacher",
                    class_id=class_id,
                ),
            ]
        )
        session.flush()
        session.add(Agent(id=agent_id, class_id=class_id, creator_id=creator_id, state="draft"))
        session.flush()
        session.add(
            AgentRevision(
                id=agent_revision_id,
                agent_id=agent_id,
                class_id=class_id,
                creator_id=creator_id,
                revision_number=1,
                name="Agent",
                system_prompt="Guide students.",
            )
        )
        session.flush()
        session.add_all(
            [
                Skill(id=skill_id, class_id=class_id, creator_id=creator_id, state="active"),
                Skill(
                    id=other_skill_id,
                    class_id=class_id,
                    creator_id=other_creator_id,
                    state="active",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                SkillRevision(
                    id=skill_revision_id,
                    skill_id=skill_id,
                    class_id=class_id,
                    creator_id=creator_id,
                    revision_number=1,
                    name="Guidance",
                    skill_type="solution_guidance",
                    instructions="Offer hints.",
                ),
                SkillRevision(
                    id=other_skill_revision_id,
                    skill_id=other_skill_id,
                    class_id=class_id,
                    creator_id=other_creator_id,
                    revision_number=1,
                    name="Other guidance",
                    skill_type="solution_guidance",
                    instructions="Offer different hints.",
                ),
            ]
        )
        session.flush()
        session.add(
            AgentSkillBinding(
                agent_revision_id=agent_revision_id,
                skill_revision_id=skill_revision_id,
                class_id=class_id,
                creator_id=creator_id,
            )
        )
        session.commit()

    with Session(engine) as session, pytest.raises(IntegrityError):
        session.add(
            AgentSkillBinding(
                agent_revision_id=agent_revision_id,
                skill_revision_id=skill_revision_id,
                class_id=class_id,
                creator_id=creator_id,
            )
        )
        session.commit()
    with Session(engine) as session, pytest.raises(IntegrityError):
        session.add(
            AgentSkillBinding(
                agent_revision_id=agent_revision_id,
                skill_revision_id=other_skill_revision_id,
                class_id=class_id,
                creator_id=creator_id,
            )
        )
        session.commit()


def test_conversation_messages_enforce_order_and_single_processing_turn() -> None:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys = ON")  # type: ignore[attr-defined]

    Base.metadata.create_all(engine)
    class_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    with Session(engine) as session:
        session.add(Class(id=class_id, name="A"))
        session.flush()
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
            ]
        )
        session.flush()
        session.add(Agent(id=agent_id, class_id=class_id, creator_id=teacher_id, state="draft"))
        session.flush()
        session.add(
            Conversation(
                id=conversation_id,
                class_id=class_id,
                student_id=student_id,
                agent_id=agent_id,
            )
        )
        session.flush()
        session.add_all(
            [
                ConversationMessage(
                    conversation_id=conversation_id,
                    class_id=class_id,
                    student_id=student_id,
                    agent_id=agent_id,
                    ordinal=1,
                    role="user",
                    state="completed",
                    content="Question",
                ),
                ConversationMessage(
                    conversation_id=conversation_id,
                    class_id=class_id,
                    student_id=student_id,
                    agent_id=agent_id,
                    ordinal=2,
                    role="assistant",
                    state="processing",
                ),
            ]
        )
        session.commit()

    with Session(engine) as session, pytest.raises(IntegrityError):
        session.add(
            ConversationMessage(
                conversation_id=conversation_id,
                class_id=class_id,
                student_id=student_id,
                agent_id=agent_id,
                ordinal=2,
                role="user",
                state="completed",
                content="Duplicate ordinal",
            )
        )
        session.commit()
    with Session(engine) as session, pytest.raises(IntegrityError):
        session.add(
            ConversationMessage(
                conversation_id=conversation_id,
                class_id=class_id,
                student_id=student_id,
                agent_id=agent_id,
                ordinal=3,
                role="assistant",
                state="processing",
            )
        )
        session.commit()


def test_agent_and_skill_lifecycle_constraints_are_declared() -> None:
    assert {
        "ck_agents_lifecycle_supported",
    } <= constraint_names("agents", CheckConstraint)
    assert {
        "ck_skills_lifecycle_supported",
        "ck_skill_revisions_type_supported",
    } <= constraint_names("skills", CheckConstraint) | constraint_names(
        "skill_revisions", CheckConstraint
    )


def test_no_server_managed_session_table_is_declared() -> None:
    assert "sessions" not in Base.metadata.tables


def test_material_constraints_and_class_list_index() -> None:
    materials = Base.metadata.tables["materials"]
    index_columns = {
        str(index.name): tuple(column.name for column in index.columns)
        for index in materials.indexes
    }
    assert index_columns["ix_materials_class_created_id"] == ("class_id", "created_at", "id")
    assert {
        "ck_materials_state_supported",
        "ck_materials_byte_size_nonnegative",
        "ck_materials_sha256_length",
    } <= constraint_names("materials", CheckConstraint)
    assert materials.c.class_id.nullable is False
    assert materials.c.uploader_id.nullable is False
