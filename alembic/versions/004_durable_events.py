"""Durable event stores — event_log, trigger_definitions, handler_invocations.

ADR-086's durable-event stores had in-memory and SQLite implementations only,
so a PostgreSQL deployment kept its event log, trigger registry and invocation
history in process memory and lost all three on restart (#135).

The DDL here is deliberately a frozen copy of `maistro.events.pg_stores._SCHEMA`
rather than an import of it: a migration must keep creating what it created on
the day it ran, and importing live application code would let a later edit
silently change what this revision does to databases that have not applied it
yet. `tests/migrations/test_event_schema_agreement.py` holds the two in step by
building both and diffing the catalogue, so the duplication is checked rather
than trusted.

Revision ID: 004
Revises: 003
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── event_log (LoggedEvent) ────────────────────────────────────
    # BIGSERIAL rather than SQLite's implicit rowid, and DOUBLE PRECISION for
    # created_at so the float epoch the dataclasses carry survives the round
    # trip unchanged. TIMESTAMPTZ would be the better column and the worse
    # match: it would make this backend return values the in-memory and SQLite
    # stores cannot, which is the divergence one conformance suite exists to
    # prevent.
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
        sa.Column("created_at", sa.Float(precision=53), nullable=False),
    )
    # (event_type, id) rather than (event_type): every read of one type is
    # ordered by id, so the index serves the ORDER BY as well as the filter.
    op.create_index("idx_event_log_type_id", "event_log", ["event_type", "id"])
    op.create_index("idx_event_log_created_at", "event_log", ["created_at"])

    # ── trigger_definitions (TriggerDefinition) ────────────────────
    op.create_table(
        "trigger_definitions",
        sa.Column("trigger_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("event_pattern", sa.Text, nullable=False, server_default=""),
        sa.Column("handler_url", sa.Text, nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("idx_trigger_enabled", "trigger_definitions", ["enabled"])

    # ── handler_invocations (HandlerInvocation) ────────────────────
    # The composite primary key is the idempotency guarantee, enforced by the
    # database rather than by the caller: it is what `ON CONFLICT` in
    # `PgInvocationStore.get_or_create` and `claim` relies on, and what makes
    # two workers racing on one redelivered event converge on a single row. A
    # surrogate key here would leave a read-then-write window instead, which
    # is the failure SQLite never had to answer for.
    #
    # `lease_expires_at` is the other half, and the key alone is not it: two
    # workers converging on one row both read it back non-terminal, and both
    # would call the handler. The lease is what hands dispatch to exactly one
    # of them, and what lets a worker that dies mid-handler be superseded
    # rather than stranding the event.
    op.create_table(
        "handler_invocations",
        sa.Column("trigger_id", sa.Text, primary_key=True),
        sa.Column("event_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(precision=53), nullable=False),
        # `sa.text("0")`, not `"0"`: a string default on a float column is
        # rendered as `'0'::double precision`, which stores differently from
        # the bare `DEFAULT 0` the store's own DDL emits. Same value, different
        # catalogue entry — and `test_event_schema_agreement` compares the
        # catalogue, which is how this was caught.
        sa.Column(
            "lease_expires_at",
            sa.Float(precision=53),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index("idx_invocations_event", "handler_invocations", ["event_id"])


def downgrade() -> None:
    op.drop_index("idx_invocations_event", table_name="handler_invocations")
    op.drop_table("handler_invocations")
    op.drop_index("idx_trigger_enabled", table_name="trigger_definitions")
    op.drop_table("trigger_definitions")
    op.drop_index("idx_event_log_created_at", table_name="event_log")
    op.drop_index("idx_event_log_type_id", table_name="event_log")
    op.drop_table("event_log")
