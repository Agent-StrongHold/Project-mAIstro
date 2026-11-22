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

Revision ID: 064
Revises: 063
Create Date: 2026-11-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_deletions",
        sa.Column("schedule_id", sa.Text, nullable=False),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("schedule_id", name="pk_schedule_deletions"),
    )


def downgrade() -> None:
    op.drop_table("schedule_deletions")
