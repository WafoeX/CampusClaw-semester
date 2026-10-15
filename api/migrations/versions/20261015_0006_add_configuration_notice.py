"""Retain the per-turn configuration change notice.

Revision ID: 20261015_0006
Revises: 20261015_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0006"
down_revision = "20261015_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column("configuration_updated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("conversation_messages", "configuration_updated")
