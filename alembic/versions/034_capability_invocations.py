"""Canonical capability Invocation ledger.

Revision ID: 034
Revises: 033
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_invocations",
        sa.Column("invocation_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("node_run_id", sa.Text, nullable=False),
        sa.Column("attempt_id", sa.Text, nullable=False),
        sa.Column("binding_id", sa.Text, nullable=False),
        sa.Column("effect_key", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("revision", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Float(precision=53), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
    )
    op.create_index(
        "idx_capability_invocation_effect",
        "capability_invocations",
        ["run_id", "node_run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
    )
    op.create_index(
        "idx_capability_invocation_attempt",
        "capability_invocations",
        ["attempt_id", "created_at", "invocation_id"],
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_capability_invocation_active_effect
           ON capability_invocations (run_id, node_run_id, binding_id, effect_key)
           WHERE status IN ('created', 'running', 'unknown')"""
    )


def downgrade() -> None:
    op.drop_index("uq_capability_invocation_active_effect", table_name="capability_invocations")
    op.drop_index("idx_capability_invocation_attempt", table_name="capability_invocations")
    op.drop_index("idx_capability_invocation_effect", table_name="capability_invocations")
    op.drop_table("capability_invocations")
