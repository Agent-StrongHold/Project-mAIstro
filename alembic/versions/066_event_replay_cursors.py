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

The statement is guarded (`CREATE TABLE IF NOT EXISTS`), matching the
adoption rule 044 states for the chain and the guarded DDL 046 carries for
the same reason: the chain-level re-application test stamps a migrated
database back and re-upgrades it, so a bare `CREATE TABLE` here fails that
walk with `DuplicateTable`. A database that already carries the table (via
an earlier `ensure_event_schema()` on a role that could create tables) is
adopted untouched; a fresh one is built to exactly the definition the store
reads.

Renumbered from 064 to 065 at the develop sync that landed the live-
Workspace-Persona revision (#12) first, and from 065 to 066 at the sync
that merged #1095's legacy-principal ownership migration: the branch had
already re-parented #12's Persona revision past its own `064` as `065`, so
this one re-parents onto that landed revision and takes the next id — a
landed trunk migration never moves, and a new id appends after the
integrated head, exactly as 065_canonical_personas itself renumbered from
034.

Revision ID: 066
Revises: 065
Create Date: 2026-10-17
"""

from __future__ import annotations

from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── event_replay_cursors (#836) ────────────────────────────────
    # `consumer_id` is the replay bridge's identity, one row per consumer.
    # `event_id` is the highest `event_log.id` acknowledged as replayed
    # (BIGINT to match `event_log.id`'s BIGSERIAL) and `updated_at` the float
    # epoch of the last acknowledgement. Frozen copy of the `_SCHEMA` block:
    # guarded so a re-application over a database that already carries the
    # table adopts it instead of failing with `DuplicateTable` (046's
    # rationale; the same walk CI's coverage (PostgreSQL) leg drives).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS event_replay_cursors (
            consumer_id TEXT PRIMARY KEY,
            event_id BIGINT NOT NULL DEFAULT 0,
            updated_at DOUBLE PRECISION NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.drop_table("event_replay_cursors")
