# pyright: basic, reportMissingImports=false
"""Relational domain model."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UserRole(StrEnum):
    TEACHER = "teacher"
    STUDENT = "student"


class MaterialState(StrEnum):
    PENDING = "pending"
    READY = "ready"


class RetrievalState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SEARCHABLE = "searchable"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class IndexVersionState(StrEnum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class IndexJobState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class AgentState(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class SkillState(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class SkillType(StrEnum):
    SOLUTION_GUIDANCE = "solution_guidance"


class ConversationMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationMessageState(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Class(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("name", name="uq_classes_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("account", name="uq_users_account"),
        CheckConstraint("role IN ('teacher', 'student')", name="role_supported"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("classes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_materials_storage_key"),
        UniqueConstraint("id", "class_id", name="uq_materials_id_class_id"),
        CheckConstraint("state IN ('pending', 'ready')", name="state_supported"),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        Index("ix_materials_class_created_id", "class_id", "created_at", "id"),
        Index("ix_materials_pending_created", "state", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MaterialState.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MaterialSearchState(Base):
    __tablename__ = "material_search_states"
    __table_args__ = (
        UniqueConstraint("material_id", name="uq_material_search_states_material_id"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'searchable', 'unsupported', 'failed')",
            name="status_supported",
        ),
        ForeignKeyConstraint(
            ["material_id", "class_id"],
            ["materials.id", "materials.class_id"],
            name="fk_material_search_states_material_class",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RetrievalState.PENDING.value
    )
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("material_index_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MaterialIndexVersion(Base):
    __tablename__ = "material_index_versions"
    __table_args__ = (
        UniqueConstraint(
            "id", "material_id", "class_id", name="uq_material_index_versions_identity"
        ),
        CheckConstraint(
            "build_state IN ('building', 'ready', 'failed')", name="build_state_supported"
        ),
        CheckConstraint("vector_dimension > 0", name="vector_dimension_positive"),
        ForeignKeyConstraint(
            ["material_id", "class_id"],
            ["materials.id", "materials.class_id"],
            name="fk_material_index_versions_material_class",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(50), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    build_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IndexVersionState.BUILDING.value
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("index_version_id", "ordinal", name="uq_knowledge_chunks_version_ordinal"),
        CheckConstraint("length(text) > 0", name="text_nonempty"),
        CheckConstraint("length(text_hash) = 64", name="text_hash_length"),
        CheckConstraint(
            "((page IS NOT NULL AND page >= 1 AND line_start IS NULL AND line_end IS NULL) "
            "OR (page IS NULL AND line_start IS NOT NULL AND line_start >= 1 "
            "AND line_end IS NOT NULL AND line_end >= line_start))",
            name="locator_family_valid",
        ),
        ForeignKeyConstraint(
            ["index_version_id", "material_id", "class_id"],
            [
                "material_index_versions.id",
                "material_index_versions.material_id",
                "material_index_versions.class_id",
            ],
            name="fk_knowledge_chunks_version_material_class",
            ondelete="CASCADE",
        ),
        Index(
            "ix_knowledge_chunks_normalized_text_trgm",
            "normalized_text",
            postgresql_using="gin",
            postgresql_ops={"normalized_text": "gin_trgm_ops"},
        ),
        Index(
            "ix_knowledge_chunks_class_version_ordinal", "class_id", "index_version_id", "ordinal"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("id", "class_id", name="uq_agents_id_class"),
        UniqueConstraint("id", "class_id", "creator_id", name="uq_agents_identity"),
        CheckConstraint("state IN ('draft', 'published', 'retired')", name="lifecycle_supported"),
        Index("ix_agents_class_creator", "class_id", "creator_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AgentState.DRAFT.value,
        server_default=AgentState.DRAFT.value,
    )
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    published_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentRevision(Base):
    __tablename__ = "agent_revisions"
    __table_args__ = (
        UniqueConstraint("agent_id", "revision_number", name="uq_agent_revisions_agent_number"),
        UniqueConstraint("id", "class_id", "creator_id", name="uq_agent_revisions_identity"),
        CheckConstraint("revision_number > 0", name="revision_number_positive"),
        ForeignKeyConstraint(
            ["agent_id", "class_id", "creator_id"],
            ["agents.id", "agents.class_id", "agents.creator_id"],
            name="fk_agent_revisions_agent_scope",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1_000), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("id", "class_id", "creator_id", name="uq_skills_identity"),
        CheckConstraint("state IN ('active', 'retired')", name="lifecycle_supported"),
        Index("ix_skills_class_creator", "class_id", "creator_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SkillState.ACTIVE.value,
        server_default=SkillState.ACTIVE.value,
    )
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("skill_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SkillRevision(Base):
    __tablename__ = "skill_revisions"
    __table_args__ = (
        UniqueConstraint("skill_id", "revision_number", name="uq_skill_revisions_skill_number"),
        UniqueConstraint("id", "class_id", "creator_id", name="uq_skill_revisions_identity"),
        CheckConstraint("revision_number > 0", name="revision_number_positive"),
        CheckConstraint("skill_type IN ('solution_guidance')", name="type_supported"),
        ForeignKeyConstraint(
            ["skill_id", "class_id", "creator_id"],
            ["skills.id", "skills.class_id", "skills.creator_id"],
            name="fk_skill_revisions_skill_scope",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_type: Mapped[str] = mapped_column(String(40), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    tools: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: ["knowledge_search"],
        server_default=text("'[\"knowledge_search\"]'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentSkillBinding(Base):
    __tablename__ = "agent_skill_bindings"
    __table_args__ = (
        UniqueConstraint(
            "agent_revision_id", "skill_revision_id", name="uq_agent_skill_bindings_pair"
        ),
        ForeignKeyConstraint(
            ["agent_revision_id", "class_id", "creator_id"],
            ["agent_revisions.id", "agent_revisions.class_id", "agent_revisions.creator_id"],
            name="fk_agent_skill_bindings_agent_revision_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["skill_revision_id", "class_id", "creator_id"],
            ["skill_revisions.id", "skill_revisions.class_id", "skill_revisions.creator_id"],
            name="fk_agent_skill_bindings_skill_revision_scope",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    skill_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    creator_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "id", "class_id", "student_id", "agent_id", name="uq_conversations_scope_identity"
        ),
        ForeignKeyConstraint(
            ["agent_id", "class_id"],
            ["agents.id", "agents.class_id"],
            name="fk_conversations_agent_class",
            ondelete="RESTRICT",
        ),
        Index("ix_conversations_student_active_created", "student_id", "deleted_at", "created_at"),
        Index("ix_conversations_agent_created", "agent_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "ordinal", name="uq_conversation_messages_ordinal"),
        UniqueConstraint("id", "class_id", name="uq_conversation_messages_id_class"),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("role IN ('user', 'assistant')", name="role_supported"),
        CheckConstraint("state IN ('processing', 'completed', 'failed')", name="state_supported"),
        ForeignKeyConstraint(
            ["conversation_id", "class_id", "student_id", "agent_id"],
            [
                "conversations.id",
                "conversations.class_id",
                "conversations.student_id",
                "conversations.agent_id",
            ],
            name="fk_conversation_messages_conversation_scope",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_conversation_messages_processing_assistant",
            "conversation_id",
            unique=True,
            postgresql_where=text("role = 'assistant' AND state = 'processing'"),
            sqlite_where=text("role = 'assistant' AND state = 'processing'"),
        ),
        Index("ix_conversation_messages_conversation_ordinal", "conversation_id", "ordinal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    retrieval_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tool_calls: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    configuration_updated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    applied_agent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessageCitation(Base):
    __tablename__ = "message_citations"
    __table_args__ = (
        UniqueConstraint("message_id", "ordinal", name="uq_message_citations_message_ordinal"),
        ForeignKeyConstraint(
            ["message_id", "class_id"],
            ["conversation_messages.id", "conversation_messages.class_id"],
            name="fk_message_citations_message_class",
            ondelete="CASCADE",
        ),
        Index("ix_message_citations_class_id", "class_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_chunks.id", ondelete="RESTRICT"), nullable=False
    )
    source_title: Mapped[str] = mapped_column(String(300), nullable=False)
    locator: Mapped[str] = mapped_column(String(300), nullable=False)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class McpServer(Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("class_id", "name", name="uq_mcp_servers_class_name"),
        UniqueConstraint("id", "class_id", name="uq_mcp_servers_id_class"),
        CheckConstraint(
            "state IN ('disconnected', 'connecting', 'connected', 'error')",
            name="state_supported",
        ),
        CheckConstraint("connection_generation >= 0", name="generation_nonnegative"),
        Index("ix_mcp_servers_class_created_id", "class_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="disconnected", server_default="disconnected"
    )
    connection_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class McpDiscoveredTool(Base):
    __tablename__ = "mcp_discovered_tools"
    __table_args__ = (
        UniqueConstraint("server_id", "generation", "name", name="uq_mcp_tools_generation_name"),
        ForeignKeyConstraint(
            ["server_id", "class_id"],
            ["mcp_servers.id", "mcp_servers.class_id"],
            name="fk_mcp_tools_server_class",
            ondelete="CASCADE",
        ),
        CheckConstraint("generation >= 0", name="generation_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class McpToolCall(Base):
    __tablename__ = "mcp_tool_calls"
    __table_args__ = (
        UniqueConstraint("assistant_message_id", "tool_ref", name="uq_mcp_calls_message_ref"),
        ForeignKeyConstraint(
            ["server_id", "class_id"],
            ["mcp_servers.id", "mcp_servers.class_id"],
            name="fk_mcp_calls_server_class",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assistant_message_id", "class_id"],
            ["conversation_messages.id", "conversation_messages.class_id"],
            name="fk_mcp_calls_message_class",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "execution_state IN ('pending', 'finalized')", name="execution_state_supported"
        ),
        CheckConstraint(
            "(execution_state = 'pending' AND status IS NULL AND code IS NULL "
            "AND completed_at IS NULL) OR (execution_state = 'finalized' "
            "AND status IS NOT NULL AND status IN ('ok', 'denied', 'error') AND code IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="terminal_consistent",
        ),
        Index("ix_mcp_calls_class_created_id", "class_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    assistant_message_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    server_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    tool_ref: Mapped[str] = mapped_column(String(264), nullable=False)
    generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MaterialIndexJob(Base):
    __tablename__ = "material_index_jobs"
    __table_args__ = (
        UniqueConstraint(
            "material_id", "desired_sha256", name="uq_material_index_jobs_material_sha"
        ),
        CheckConstraint(
            "state IN ('pending', 'processing', 'complete', 'failed')", name="state_supported"
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        ForeignKeyConstraint(
            ["material_id", "class_id"],
            ["materials.id", "materials.class_id"],
            name="fk_material_index_jobs_material_class",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    desired_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IndexJobState.PENDING.value
    )
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
