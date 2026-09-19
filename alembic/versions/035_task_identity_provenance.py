"""Persist task actor and service delegation evidence (#1057).

Revision ID: 035
Revises: 034
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("user_id", sa.String(200), nullable=False, server_default=""),
    )
    op.add_column("tasks", sa.Column("service_principal_id", sa.String(200), nullable=True))
    op.add_column("tasks", sa.Column("delegation_id", sa.String(128), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("actor_kind", sa.String(20), nullable=False, server_default="user"),
    )
    op.alter_column("tasks", "user_id", server_default=None)
    op.alter_column("tasks", "actor_kind", server_default=None)


def downgrade() -> None:
    op.drop_column("tasks", "actor_kind")
    op.drop_column("tasks", "delegation_id")
    op.drop_column("tasks", "service_principal_id")
    op.drop_column("tasks", "user_id")
