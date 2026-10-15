"""Persist bounded current-turn citation presentation snapshots.

Revision ID: 20261015_0005
Revises: 795c614af378
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0005"
down_revision = "795c614af378"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_citations",
        sa.Column("source_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.alter_column("message_citations", "source_snapshot", server_default=None)


def downgrade() -> None:
    op.drop_column("message_citations", "source_snapshot")
