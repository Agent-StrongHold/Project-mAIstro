"""Persist governed capability Invocations (#1088).

Revision ID: 034
Revises: 033
Create Date: 2026-09-11

The handler delivery ledger is a different Invocation type. This table stores
one canonical capability effect, including resolved provider and usage metadata,
so model evaluator and provider health calls remain auditable after restart.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None

_TABLE = "capability_invocations"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("invocation_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("node_run_id", sa.Text(), nullable=False),
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("binding_id", sa.Text(), nullable=False),
        sa.Column("effect_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_capability_invocation_effect",
        _TABLE,
        ["run_id", "node_run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
    )
    op.create_index(
        "idx_capability_invocation_attempt",
        _TABLE,
        ["attempt_id", "created_at", "invocation_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_capability_invocation_attempt", table_name=_TABLE)
    op.drop_index("idx_capability_invocation_effect", table_name=_TABLE)
    op.drop_table(_TABLE)
