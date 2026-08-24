"""One Run per schedule firing, enforced by the database (#220, ADR-082426-82c7).

#218 gave `ScheduleRunAdmitter` the durability half of #46's "each firing has
exactly one canonical run_id": Runs are created before the cursor advances, so
a crash between them repeats an occurrence rather than skipping it. Repeating
was the deliberate choice — a skip is silent and permanent — but nothing
bounded the repeat, and nothing serialised two tickers evaluating the same due
window.

Both are the same missing thing: the unit being claimed was the *cursor*, and a
cursor is not the identity of an occurrence. `(schedule_id, scheduled_for)` is,
and this index makes it one.

Expression index over the payload rather than two new columns. The pair belongs
to one admitter — every task and chat Run would carry them as NULL — and the
`jsonb ->> text` operators are IMMUTABLE, so PostgreSQL accepts them in an
index where migration 013's `text::timestamptz` was refused.

Partial on both keys being present, for the same reason: without the predicate
every Run that is not scheduled would collide on `(NULL, NULL)`.

`catchup` is deliberately not in the key. A backfill and an on-time fire for
the same nominal time are the same occurrence; that they were noticed at
different moments is why the flag exists, not a reason to run the work twice.

The upgrade needs no backfill and can only fail on a database that already
holds duplicate occurrences — which is the defect being closed, and is worth
failing loudly rather than silently keeping.

Revision ID: 015
Revises: 014
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

_SCHEDULE_ID = "(payload -> 'provenance' ->> 'schedule_id')"
_SCHEDULED_FOR = "(payload -> 'provenance' ->> 'scheduled_for')"
_INDEX = "ix_canonical_runs_occurrence"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
            ON canonical_runs ({_SCHEDULE_ID}, {_SCHEDULED_FOR})
            WHERE {_SCHEDULE_ID} IS NOT NULL
              AND {_SCHEDULED_FOR} IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
