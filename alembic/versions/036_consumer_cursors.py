"""Durable consumer cursors — consumer_cursors.

The legacy-event replay bridge (`Container.process_durable_events`, ADR-086)
kept its resume position as a process-local int, so every restart replayed
`event_log` from zero (#1163). The position now lives in `consumer_cursors`,
one row per consumer, together with the claim lease and fencing token that
let exactly one replica advance it at a time.

Revision 004 created the other three event tables and this table is created
the same way: the DDL is a frozen copy of the `consumer_cursors` block in
`maistro.events.pg_stores._SCHEMA`, not an import of it, because a migration
must keep creating what it created on the day it ran.
`tests/migrations/test_event_schema_agreement.py` builds both and diffs the
catalogue, so the duplication is checked rather than trusted. A deployment
whose application role cannot create tables (migrations run under a
privileged role) needs this revision applied before the upgraded application
starts; `ensure_event_schema`'s `CREATE TABLE IF NOT EXISTS` then finds the
table already present.

Revision ID: 036_consumer_cursors
Revises: 035_outcome_scope_thumb_index
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036_consumer_cursors"
down_revision = "035_outcome_scope_thumb_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── consumer_cursors (CursorLease) ─────────────────────────────
    # `position` is the last `event_log.id` every matching trigger has
    # settled for this consumer; `holder`, `fencing_token` and
    # `lease_expires_at` are the claim lease that makes `advance` refuse a
    # write from a replica whose lease was already taken over. BIGINT to
    # match `event_log.id`'s BIGSERIAL. `sa.text("0")` rather than `"0"` on
    # both numeric defaults, for the reason revision 004 gives: a string
    # default renders as a quoted literal, which the catalogue records
    # differently from the bare `DEFAULT 0` the store's own DDL emits.
    op.create_table(
        "consumer_cursors",
        sa.Column("consumer_id", sa.Text, primary_key=True),
        sa.Column("position", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("holder", sa.Text, nullable=False, server_default=""),
        sa.Column("fencing_token", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "lease_expires_at",
            sa.Float(precision=53),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_table("consumer_cursors")
