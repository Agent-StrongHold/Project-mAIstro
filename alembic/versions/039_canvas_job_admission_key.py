"""Make canonical Canvas job admission identities unique (#1055 review).

Canvas admission (`CanvasCanonicalExecution.admit`) looks an existing Run up by
its deterministic `canvas_job_id` before creating a new one, but that lookup is
a scan with no lock: two workers racing the same `Idempotency-Key` can both
pass the check before either inserts, leaving two canonical Runs that agree on
one `canvas_job_id`. Only one Canvas job (the durable receipt, primary-keyed by
that same id) can ever be created for it, so the losing Run is silently
orphaned -- and reconciling it used to raise and abort the whole tick, because
nothing durable said the id could only ever name one Run.

Same shape as migrations 015 (schedule occurrences) and 037 (delegation
admission): the unique index *is* the claim. `CanvasCanonicalExecution.admit`
now inserts first and re-reads the durable scan on conflict, adopting whichever
Run actually won the index, instead of trusting a check-then-insert.

Scoped to `admission_source = 'canvas_generation'` as well as a non-null
`canvas_job_id`, not the field alone: `canvas_job_id` is not an exclusively
Canvas-owned name at the schema level, and a Run from an unrelated source that
happens to carry the same string in its own provenance (accidentally or, as
the adapter's own tests deliberately model, an impersonation attempt) must
not be able to block a real Canvas admission from claiming it.

Revision ID: 039
Revises: 038
Create Date: 2026-09-21
"""

from __future__ import annotations

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None

_INDEX = "ix_canonical_runs_canvas_job"
_KEY = "(payload -> 'provenance' ->> 'canvas_job_id')"
_SOURCE = "(payload -> 'provenance' ->> 'admission_source')"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
            ON canonical_runs ({_KEY})
            WHERE {_KEY} IS NOT NULL AND {_SOURCE} = 'canvas_generation'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
