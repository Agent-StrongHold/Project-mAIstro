"""Persist the canonical Event envelope and Workspace sequence authority (#61).

Revision ID: 030
Revises: 029
Create Date: 2026-08-31

The ADR-086 ``event_log`` remains a compatibility delivery log for triggers and
handler invocations. This table is different on purpose: one row is one
canonical ``EventEnvelope`` and ``(stream_id, sequence)`` is the durable ordering
authority. Compatibility buses may project this identity but must not mint a
second universal sequence.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None

_TABLE = "canonical_event_log"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("stream_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("stream_scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("project_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("run_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("node_run_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("attempt_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("invocation_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("session_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("correlation_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("causation_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor_id", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("stream_id", "sequence", name="uq_canonical_event_stream_sequence"),
    )
    op.create_index(
        "idx_canonical_event_stream",
        _TABLE,
        ["stream_id", "sequence"],
    )
    op.create_index(
        "idx_canonical_event_run",
        _TABLE,
        ["run_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("idx_canonical_event_run", table_name=_TABLE)
    op.drop_index("idx_canonical_event_stream", table_name=_TABLE)
    op.drop_table(_TABLE)
