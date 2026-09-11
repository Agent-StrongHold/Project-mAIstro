"""Durable Workspace lifecycle state for crash reconciliation (#1121).

The Workspace row and its Root Project are owned by different stores, so they
cannot share a PostgreSQL transaction through the public store protocol.  This
journal makes the boundary explicit: ``creating`` and ``deleting`` rows are
never visible through the canonical Workspace store and are retried during
startup until both halves converge.

Revision ID: 034
Revises: 033
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_workspace_lifecycle",
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="active"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["canonical_workspaces.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "state IN ('creating', 'active', 'deleting')",
            name="canonical_workspace_lifecycle_state_check",
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO canonical_workspace_lifecycle (workspace_id, state)
            SELECT workspace_id, 'active' FROM canonical_workspaces
            """
        )
    )


def downgrade() -> None:
    op.drop_table("canonical_workspace_lifecycle")
