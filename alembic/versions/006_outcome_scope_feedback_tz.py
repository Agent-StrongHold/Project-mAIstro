"""Give outcomes the scope, feedback and timestamp type their store needs (#122).

Three defects found by review once #122 made `PgOutcomeStore` the production
outcome store, all verified against PostgreSQL 18.6 with 001-005 applied.

**1. `created_at` was `TIMESTAMP WITHOUT TIME ZONE`.** Migration 001 declares a
plain `sa.DateTime`, and every read in `PgOutcomeStore` compares against
`datetime.now(UTC) - timedelta(...)`, which is offset-aware. asyncpg cannot
encode an aware datetime for a naive column, so the wired store could record
outcomes and then fail every read:

    get_experience_context -> DataError: can't subtract offset-naive and
                              offset-aware datetimes

TIMESTAMPTZ rather than making the callers naive, because these rows are
compared across processes that need not share a timezone, and "naive means
UTC" is a convention no column can enforce. `USING created_at AT TIME ZONE
'UTC'` reads existing rows as the UTC they were written as.

**2. No scope columns.** `Outcome` carries `project_id`, and `record()` dropped
it. `get_experience_context(org_id=..., project_id=...)` accepted both and
filtered on neither, so a failure narrative injected into one project's prompt
could come from another project -- or another org. `InMemoryOutcomeStore`
filters on both, so this was also two implementations of one protocol
disagreeing about what scoping means.

**3. No feedback columns.** `thumb`, `thumb_comment`, `node_id`, `dag_id`,
`dag_run_id` and `eval_judge_score` exist on `Outcome` and had nowhere to go.
That is not merely lossy: `InMemoryOutcomeStore.get_experience_context`
surfaces hard failures *and* thumbs-down outcomes, so without `thumb` the
PostgreSQL store cannot implement half its contract. A thumbs-down accepted by
the feedback service became an ordinary successful row.

Every column is added with a server default, because they are written by raw
INSERTs rather than through the ORM -- see 005's note on why `default=` in
migration 001 emits no DDL default.

Revision ID: 006_outcome_scope_feedback
Revises: 005_pg_store_alignment
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006_outcome_scope_feedback"
down_revision = "005_pg_store_alignment"
branch_labels = None
depends_on = None

#: Scope and telemetry identifiers, all NOT NULL DEFAULT '' so a raw INSERT
#: that omits them still lands and an absent scope reads as "unscoped" rather
#: than NULL -- which would silently drop rows from an `= $n` predicate.
_TEXT_COLUMNS = ("project_id", "dag_id", "dag_run_id", "node_id", "thumb", "thumb_comment")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE outcomes ALTER COLUMN created_at TYPE TIMESTAMPTZ "
        "USING created_at AT TIME ZONE 'UTC'"
    )

    for name in _TEXT_COLUMNS:
        op.add_column("outcomes", sa.Column(name, sa.Text, nullable=False, server_default=""))
    # Nullable on purpose: None means the eval judge did not run, which is not
    # the same as a score of 0.0.
    op.add_column("outcomes", sa.Column("eval_judge_score", sa.Float, nullable=True))

    # get_experience_context filters task_type + created_at + org_id +
    # project_id together; this is the composite that predicate walks.
    op.create_index(
        "ix_outcomes_scope_task_time",
        "outcomes",
        ["org_id", "project_id", "task_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outcomes_scope_task_time", table_name="outcomes")
    op.drop_column("outcomes", "eval_judge_score")
    for name in reversed(_TEXT_COLUMNS):
        op.drop_column("outcomes", name)
    op.execute(
        "ALTER TABLE outcomes ALTER COLUMN created_at TYPE TIMESTAMP "
        "USING created_at AT TIME ZONE 'UTC'"
    )
