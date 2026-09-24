# pyright: basic, reportMissingImports=false
"""Class-scoped material persistence queries."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from campusclaw.domain.models import Material, MaterialState


class MaterialRepository:
    """Require the caller's class for every material read query."""

    def list_ready(self, session: Session, class_id: uuid.UUID) -> list[Material]:
        statement = (
            select(Material)
            .where(Material.class_id == class_id, Material.state == MaterialState.READY.value)
            .order_by(Material.created_at.desc(), Material.id.desc())
        )
        return list(session.scalars(statement).all())

    def get_metadata(
        self,
        session: Session,
        class_id: uuid.UUID,
        material_id: uuid.UUID,
    ) -> Material | None:
        statement = select(Material).where(
            Material.class_id == class_id,
            Material.id == material_id,
            Material.state == MaterialState.READY.value,
        )
        return session.scalar(statement)

    def get_for_download(
        self,
        session: Session,
        class_id: uuid.UUID,
        material_id: uuid.UUID,
    ) -> Material | None:
        """Use the same class predicate before a file path is ever opened."""
        statement = select(Material).where(
            Material.class_id == class_id,
            Material.id == material_id,
            Material.state == MaterialState.READY.value,
        )
        return session.scalar(statement)
