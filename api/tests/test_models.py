# pyright: basic, reportMissingImports=false
from sqlalchemy import CheckConstraint, Constraint, UniqueConstraint

from campusclaw.domain.models import Base


def constraint_names(table_name: str, kind: type[Constraint]) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {
        str(constraint.name) for constraint in table.constraints if isinstance(constraint, kind)
    }


def test_complete_model_metadata() -> None:
    assert set(Base.metadata.tables) == {"classes", "users", "sessions", "materials"}


def test_user_membership_role_and_uniqueness_constraints() -> None:
    users = Base.metadata.tables["users"]
    assert users.c.class_id.nullable is False
    assert users.c.class_id.foreign_keys.pop().target_fullname == "classes.id"
    assert "ck_users_role_supported" in constraint_names("users", CheckConstraint)
    assert "uq_users_account" in constraint_names("users", UniqueConstraint)


def test_session_lookup_and_expiry_indexes() -> None:
    sessions = Base.metadata.tables["sessions"]
    index_columns = {
        str(index.name): tuple(column.name for column in index.columns)
        for index in sessions.indexes
    }
    assert index_columns["ix_sessions_expires_at"] == ("expires_at",)
    assert "uq_sessions_token_digest" in constraint_names("sessions", UniqueConstraint)


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
