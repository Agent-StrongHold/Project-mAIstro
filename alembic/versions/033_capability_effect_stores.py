"""Persist canonical capability effect stores (#1133).

Revision ID: 033
Revises: 032
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_bindings",
        sa.Column("binding_id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("project_id", sa.Text, nullable=False),
        sa.Column("node_id", sa.Text, nullable=False, server_default=""),
        sa.Column("capability", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
    )
    op.create_table(
        "capability_invocations",
        sa.Column("invocation_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("node_run_id", sa.Text, nullable=False),
        sa.Column("attempt_id", sa.Text, nullable=False),
        sa.Column("binding_id", sa.Text, nullable=False),
        sa.Column("effect_key", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", sa.Float(precision=53), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "node_run_id",
            "binding_id",
            "effect_key",
            name="uq_capability_invocation_effect",
        ),
    )
    op.create_index(
        "idx_capability_invocation_attempt",
        "capability_invocations",
        ["attempt_id", "created_at", "invocation_id"],
    )
    op.create_table(
        "capability_approvals",
        sa.Column("request_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("node_run_id", sa.Text, nullable=False),
        sa.Column("binding_id", sa.Text, nullable=False),
        sa.Column("effect_key", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "node_run_id",
            "binding_id",
            "effect_key",
            name="uq_capability_approval_effect",
        ),
    )


def downgrade() -> None:
    op.drop_table("capability_approvals")
    op.drop_index("idx_capability_invocation_attempt", table_name="capability_invocations")
    op.drop_table("capability_invocations")
    op.drop_table("capability_bindings")
