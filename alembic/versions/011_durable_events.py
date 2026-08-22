"""Durable events in PostgreSQL (#135).

ADR-086's stores existed in two flavours — in-memory and SQLite — and the
container selected between them on "is a SQLite connection open". A deployment
on PostgreSQL, the durable system of record, therefore got **in-memory** durable
events: the event log, the trigger registry and the invocation history all lost
on restart. "Durable events that are not durable" is the shape of claim #122 was
filed about, one layer up.

`handler_invocations` carries the weight. Its composite primary key is the
idempotency key — one invocation per (trigger, event) — and it is what makes a
redelivered event recognisable as already handled. In-memory that guarantee held
only within one process lifetime and only for one process, so any deployment
with more than one worker did not have it at all.

Column shapes follow each store's SQLite twin, with two type changes PostgreSQL
requires: `id` becomes a generated identity rather than AUTOINCREMENT, and the
JSON payload becomes JSONB rather than a TEXT blob the application encodes.

Revision ID: 011
Revises: 010
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── event_log ──────────────────────────────────────────────────
    # `id` doubles as the replay cursor for the processing loop, so it has to be
    # monotonic and gap-tolerant rather than merely unique.
    op.create_table(
        "event_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text, nullable=False, server_default=""),
        sa.Column("entity_id", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("source", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.Double, nullable=False),
    )
    op.create_index("ix_event_log_type_time", "event_log", ["event_type", "created_at"])
    # The replay loop's own query: everything after a cursor, in id order.
    op.create_index("ix_event_log_created_at", "event_log", ["created_at"])

    # ── trigger_definitions ────────────────────────────────────────
    op.create_table(
        "trigger_definitions",
        sa.Column("trigger_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("event_pattern", sa.Text, nullable=False, server_default=""),
        sa.Column("handler_url", sa.Text, nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    # `get_matching` loads the enabled ones and filters in Python, because glob
    # semantics are not expressible in portable SQL. Indexing the filter it
    # *can* push down keeps that from being a full scan.
    op.create_index(
        "ix_trigger_definitions_enabled",
        "trigger_definitions",
        ["trigger_id"],
        postgresql_where=sa.text("enabled"),
    )

    # ── handler_invocations ────────────────────────────────────────
    # The composite primary key IS the idempotency guarantee. Two workers
    # handed the same event both call get_or_create; the key is what makes them
    # converge on one row instead of each starting its own handler run.
    op.create_table(
        "handler_invocations",
        sa.Column("trigger_id", sa.Text, primary_key=True),
        sa.Column("event_id", sa.BigInteger, primary_key=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.Double, nullable=False),
    )
    op.create_index("ix_handler_invocations_event", "handler_invocations", ["event_id"])
    # Recovery scans for invocations left mid-flight; without this that is a
    # sequential scan of every invocation the deployment has ever recorded.
    op.create_index(
        "ix_handler_invocations_live",
        "handler_invocations",
        ["status"],
        postgresql_where=sa.text("status NOT IN ('success', 'failed')"),
    )


def downgrade() -> None:
    op.drop_table("handler_invocations")
    op.drop_table("trigger_definitions")
    op.drop_table("event_log")
