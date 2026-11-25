"""Durable Schedule deletion markers (#2467).

`schedules` deletions were previously indistinguishable from "never
existed": a Hive projection row that outlived its canonical counterpart
(a route crash between the canonical delete and the Hive `pop`) looked
exactly like a legacy row awaiting first import, and startup backfill
re-created the deleted schedule from it — reverting a deliberate delete and
re-arming its recurrence.

`schedule_deletions` is the durable marker that closes that ambiguity:
`PgScheduleStore.delete` records the id here in the same transaction that
removes the row, and startup refuses to import any projection row whose id
appears here. A later `put` of the same id clears the marker, so a genuine
re-create is never blocked by the old delete. The SQLite store declares the
identical table in its own `CREATE TABLE` DDL, per the dual-ship convention
(016 for `schedules`; workspace/goal stores follow the same pattern).

Written as `064` on this branch's previous tip; develop landed `064` through
`068` in the meantime (personas, replay cursors, receipts, delegation grants,
legacy-principal ownership), and a landed trunk migration never moves — so
this unlanded revision renumbers onto that tip as `069`.

Revision ID: 069
Revises: 068
Create Date: 2026-11-22
"""

from __future__ import annotations

from alembic import op

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, like 063/064: stamp-back and re-upgrade is a live repair
    # path, and the chain's contract is that re-applying a revision over the
    # schema it already built is adoption, not an error
    # (tests/migrations/test_migration_chain.py drives exactly that walk).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_deletions (
            schedule_id TEXT NOT NULL,
            deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT pk_schedule_deletions PRIMARY KEY (schedule_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS schedule_deletions")
