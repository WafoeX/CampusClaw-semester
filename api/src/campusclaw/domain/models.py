# pyright: basic, reportMissingImports=false
"""Relational domain model."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
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
