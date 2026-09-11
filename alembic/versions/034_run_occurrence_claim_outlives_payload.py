"""The occurrence claim outlives the payload (#1059 review, #220, #273).

Migration 015 made one Run per schedule firing a database fact with a unique
expression index over `payload -> 'provenance' ->> 'schedule_id'` and
`... ->> 'scheduled_for'`. Migration 017 then gave the archive tier the right
to set `payload` to NULL once a terminal Run goes cold. Together they released
the claim exactly when it was least visible: an archived winner no longer
occupied the index, so a scheduler recovering late enough — a ticker that died
between `create_run` and `record_fire`, with a catch-up window longer than the
archive horizon — inserted a second canonical Run for an occurrence that had
already run, and `get_run_for_occurrence` could not find the first.

The claim is promoted into two nullable columns written once at creation, the
way `retention_expires_at` already is (migration 012), and the unique partial
index is rebuilt over them under the same name so `PgRunStore` keeps matching
`ix_canonical_runs_occurrence` on a refused insert. Archiving touches only
`payload`, so the columns — and the claim — outlive it. Existing rows are
backfilled from the payload they still carry; a row archived before this
migration has no payload to read, and its claim was already gone.

Revision ID: 034
Revises: 033
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None

_INDEX = "ix_canonical_runs_occurrence"
_SCHEDULE_ID = "(payload -> 'provenance' ->> 'schedule_id')"
_SCHEDULED_FOR = "(payload -> 'provenance' ->> 'scheduled_for')"


def upgrade() -> None:
    op.add_column("canonical_runs", sa.Column("schedule_id", sa.Text, nullable=True))
    op.add_column("canonical_runs", sa.Column("scheduled_for", sa.Text, nullable=True))
    op.execute(
        sa.text(
            f"""
            UPDATE canonical_runs
               SET schedule_id = {_SCHEDULE_ID}, scheduled_for = {_SCHEDULED_FOR}
             WHERE payload IS NOT NULL
               AND {_SCHEDULE_ID} IS NOT NULL
               AND {_SCHEDULED_FOR} IS NOT NULL
            """
        )
    )
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
            ON canonical_runs (schedule_id, scheduled_for)
            WHERE schedule_id IS NOT NULL AND scheduled_for IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
            ON canonical_runs ({_SCHEDULE_ID}, {_SCHEDULED_FOR})
            WHERE {_SCHEDULE_ID} IS NOT NULL
              AND {_SCHEDULED_FOR} IS NOT NULL
        """
    )
    op.drop_column("canonical_runs", "scheduled_for")
    op.drop_column("canonical_runs", "schedule_id")
