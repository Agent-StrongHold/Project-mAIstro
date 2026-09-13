"""Persist dispatch inputs needed to restore queued task receipts (#1057).

Revision ID: 036
Revises: 035
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("task_type", sa.String(200), nullable=True))
    op.add_column("tasks", sa.Column("agent_id", sa.String(200), nullable=True))
    op.add_column("tasks", sa.Column("capability", sa.String(200), nullable=True))
    op.add_column("tasks", sa.Column("program_context", postgresql.JSONB, nullable=True))
    op.add_column(
        "tasks",
        sa.Column("lane", sa.String(20), nullable=False, server_default="background"),
    )
    op.add_column(
        "tasks",
        sa.Column("priority_tier", sa.String(2), nullable=False, server_default="P2"),
    )
    op.add_column("tasks", sa.Column("session_id", sa.String(200), nullable=True))
    op.alter_column("tasks", "lane", server_default=None)
    op.alter_column("tasks", "priority_tier", server_default=None)


def downgrade() -> None:
    op.drop_column("tasks", "session_id")
    op.drop_column("tasks", "priority_tier")
    op.drop_column("tasks", "lane")
    op.drop_column("tasks", "program_context")
    op.drop_column("tasks", "capability")
    op.drop_column("tasks", "agent_id")
    op.drop_column("tasks", "task_type")
