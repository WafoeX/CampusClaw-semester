# pyright: basic, reportMissingImports=false
from sqlalchemy import CheckConstraint, Constraint, UniqueConstraint

from campusclaw.domain.models import Base


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
