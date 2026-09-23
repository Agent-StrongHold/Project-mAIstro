"""Manual fires claim occurrences by their own identity, not a fake instant.

#1120. The occurrence claim (migration 015) made `(schedule_id, scheduled_for)`
the identity of a firing, which is right for a nominal cron occurrence and
wrong for a manual one: a manual fire has no cron time, and minting
`datetime.now()` per request gave every retry of the same logical fire a
*different* identity — the exact mechanism by which a double submit became two
Runs.

So a manual fire now carries `schedule_fire_id`, an opaque token stable across
retries, and claims `(schedule_id, 'manual:' + schedule_fire_id)`. The `manual:`
prefix keeps the two identity spaces disjoint: a manual token can never collide
with, and thereby consume, a nominal occurrence's slot.

One index still enforces both claims — the expression becomes
`COALESCE('manual:' || fire_id, scheduled_for)`. `'manual:' || NULL` is NULL in
PostgreSQL, so a scheduled Run's claim expression is unchanged byte for byte,
and rows written before this migration keep their claims. The old index is
dropped rather than added beside, because two unique indexes over the same
insert would each refuse a different pair of duplicates, and the loser of that
races is whichever the caller did not expect.

The upgrade needs no backfill: every existing Run was fired by the recurring
path and carries `scheduled_for` with no `schedule_fire_id`, so its claim
expression is identical under the new index. Like 015, this can only fail on a
database that already holds two Runs for one manual firing — which is the
defect being closed, and is worth failing loudly rather than silently keeping.

Revision ID: 042
Revises: 036_audit_log_org_scope
Create Date: 2026-09-12

Renumbered three times after develop took each parent id while this branch
was open: from 034 (#1056 landed `034_hitl_deadline_index`; both declared
`down_revision = "033"`, two heads — the same collision #1341 resolved before
by renumbering), then from 039 (#1531 landed `039_canvas_job_admission_key`;
both declared `down_revision = "038"`, two heads at 038 — the same collision
revision 040's own docstring records), then from 041 onto `036_audit_log_org_scope`
(develop's #1395 re-parented that migration onto `040`, so following `040`
here would fork the chain into the "multiple head revisions" failure every
deployment hits). The id keeps the develop chain linear with this as the
single head. Only the identifiers change; the DDL this applies is untouched.
"""

from __future__ import annotations

from alembic import op

revision = "042"
down_revision = "036_audit_log_org_scope"
branch_labels = None
depends_on = None

_SCHEDULE_ID = "(payload -> 'provenance' ->> 'schedule_id')"
_FIRE_ID = "(payload -> 'provenance' ->> 'schedule_fire_id')"
_SCHEDULED_FOR = "(payload -> 'provenance' ->> 'scheduled_for')"
_OCCURRENCE = f"COALESCE('manual:' || {_FIRE_ID}, {_SCHEDULED_FOR})"
_INDEX = "ix_canonical_runs_occurrence"


def upgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
            ON canonical_runs ({_SCHEDULE_ID}, {_OCCURRENCE})
            WHERE {_SCHEDULE_ID} IS NOT NULL
              AND COALESCE({_FIRE_ID}, {_SCHEDULED_FOR}) IS NOT NULL
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
