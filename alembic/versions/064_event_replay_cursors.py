"""Durable legacy replay acknowledgement — event_replay_cursors.

The legacy-event replay bridge (#836) used to acknowledge settled
`event_log` events only through `ensure_event_schema()`'s runtime
`CREATE TABLE IF NOT EXISTS`. That fails a deployment whose application role
cannot create tables (migrations applied under a privileged role, the same
shape revision 036 documents for `consumer_cursors`): startup reaches
`ensure_event_schema()`, the DDL is rejected, and the bridge never comes up.
This revision creates the table the managed way; the runtime statement then
finds it present.

As with 004 and 036, the DDL is a frozen copy of the `event_replay_cursors`
block in `maistro.events.pg_stores._SCHEMA`, not an import of it, and
`tests/migrations/test_event_schema_agreement.py` diffs the two catalogues.

Revision ID: 064
Revises: 063
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── event_replay_cursors (#836) ────────────────────────────────
    # `consumer_id` is the replay bridge's identity, one row per consumer.
    # `event_id` is the highest `event_log.id` acknowledged as replayed
    # (BIGINT to match `event_log.id`'s BIGSERIAL) and `updated_at` the float
    # epoch of the last acknowledgement. `sa.text("0")` rather than `"0"` on
    # the numeric default for the reason revision 004 gives: a string default
    # renders as a quoted literal, which the catalogue records differently
    # from the bare `DEFAULT 0` the store's own DDL emits.
    op.create_table(
        "event_replay_cursors",
        sa.Column("consumer_id", sa.Text, primary_key=True),
        sa.Column("event_id", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.Float(precision=53), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("event_replay_cursors")
