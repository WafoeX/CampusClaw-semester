"""Add class-scoped retrieval state, versions, chunks, and durable jobs.

PostgreSQL remains authoritative for text and provenance; vectors are a derived Qdrant index.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260929_0003"
down_revision: str | None = "20260929_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_unique_constraint("uq_materials_id_class_id", "materials", ["id", "class_id"])

    op.create_table(
        "material_index_versions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("material_id", UUID, nullable=False),
        sa.Column("class_id", UUID, nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("extraction_version", sa.String(50), nullable=False),
        sa.Column("chunking_version", sa.String(50), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("vector_dimension", sa.Integer(), nullable=False),
        sa.Column("build_state", sa.String(20), nullable=False, server_default="building"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "build_state IN ('building', 'ready', 'failed')",
            name="ck_material_index_versions_build_state_supported",
        ),
        sa.CheckConstraint(
            "vector_dimension > 0", name="ck_material_index_versions_vector_dimension_positive"
        ),
        sa.ForeignKeyConstraint(
            ["material_id", "class_id"], ["materials.id", "materials.class_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_index_versions"),
        sa.UniqueConstraint(
            "id", "material_id", "class_id", name="uq_material_index_versions_identity"
        ),
    )
    op.create_index("ix_material_index_versions_class_id", "material_index_versions", ["class_id"])

    op.create_table(
        "material_search_states",
        sa.Column("id", UUID, nullable=False),
        sa.Column("material_id", UUID, nullable=False),
        sa.Column("class_id", UUID, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("active_version_id", UUID, nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'searchable', 'unsupported', 'failed')",
            name="ck_material_search_states_status_supported",
        ),
        sa.ForeignKeyConstraint(
            ["material_id", "class_id"], ["materials.id", "materials.class_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["active_version_id"], ["material_index_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_search_states"),
        sa.UniqueConstraint("material_id", name="uq_material_search_states_material_id"),
    )
    op.create_index("ix_material_search_states_class_id", "material_search_states", ["class_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("index_version_id", UUID, nullable=False),
        sa.Column("material_id", UUID, nullable=False),
        sa.Column("class_id", UUID, nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("section_label", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(text) > 0", name="ck_knowledge_chunks_text_nonempty"),
        sa.CheckConstraint("length(text_hash) = 64", name="ck_knowledge_chunks_text_hash_length"),
        sa.CheckConstraint(
            "((page IS NOT NULL AND page >= 1 AND line_start IS NULL AND line_end IS NULL) "
            "OR (page IS NULL AND line_start IS NOT NULL AND line_start >= 1 "
            "AND line_end IS NOT NULL AND line_end >= line_start))",
            name="ck_knowledge_chunks_locator_family_valid",
        ),
        sa.ForeignKeyConstraint(
            ["index_version_id", "material_id", "class_id"],
            [
                "material_index_versions.id",
                "material_index_versions.material_id",
                "material_index_versions.class_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_chunks"),
        sa.UniqueConstraint(
            "index_version_id", "ordinal", name="uq_knowledge_chunks_version_ordinal"
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_class_version_ordinal",
        "knowledge_chunks",
        ["class_id", "index_version_id", "ordinal"],
    )
    op.create_index(
        "ix_knowledge_chunks_normalized_text_trgm",
        "knowledge_chunks",
        ["normalized_text"],
        postgresql_using="gin",
        postgresql_ops={"normalized_text": "gin_trgm_ops"},
    )

    op.create_table(
        "material_index_jobs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("material_id", UUID, nullable=False),
        sa.Column("class_id", UUID, nullable=False),
        sa.Column("desired_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'processing', 'complete', 'failed')",
            name="ck_material_index_jobs_state_supported",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_material_index_jobs_attempts_nonnegative"),
        sa.ForeignKeyConstraint(
            ["material_id", "class_id"], ["materials.id", "materials.class_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_index_jobs"),
        sa.UniqueConstraint(
            "material_id", "desired_sha256", name="uq_material_index_jobs_material_sha"
        ),
    )
    op.create_index("ix_material_index_jobs_class_id", "material_index_jobs", ["class_id"])


def downgrade() -> None:
    op.drop_index("ix_material_index_jobs_class_id", table_name="material_index_jobs")
    op.drop_table("material_index_jobs")
    op.drop_index("ix_knowledge_chunks_normalized_text_trgm", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_class_version_ordinal", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_material_search_states_class_id", table_name="material_search_states")
    op.drop_table("material_search_states")
    op.drop_index("ix_material_index_versions_class_id", table_name="material_index_versions")
    op.drop_table("material_index_versions")
    op.drop_constraint("uq_materials_id_class_id", "materials", type_="unique")
