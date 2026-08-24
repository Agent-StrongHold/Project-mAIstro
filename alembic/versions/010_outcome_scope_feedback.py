"""Give outcomes the scope and feedback columns their store needs (#122).

Two defects found by review once #122 made `PgOutcomeStore` the production
outcome store, both verified against PostgreSQL 18.6.

**1. No scope columns.** `Outcome` carries `project_id`, and `record()` dropped
it. `get_experience_context(org_id=..., project_id=...)` accepted both and
filtered on neither, so a failure narrative injected into one project's prompt
could come from another project — or another org. `InMemoryOutcomeStore`
filters on both, so this was also two implementations of one protocol
disagreeing about what scoping means.

**2. No feedback columns.** `thumb`, `thumb_comment`, `node_id`, `dag_id`,
`dag_run_id` and `eval_judge_score` exist on `Outcome` and had nowhere to go.
That is not merely lossy: `InMemoryOutcomeStore.get_experience_context`
surfaces hard failures *and* thumbs-down outcomes, so without `thumb` the
PostgreSQL store cannot implement half its contract. A thumbs-down accepted by
the feedback service became an ordinary successful row and could never reach
the learning loop.

The third defect this migration originally carried — `created_at` being
`TIMESTAMP WITHOUT TIME ZONE`, which asyncpg cannot compare against the aware
datetimes every read builds — landed separately as revision `006`, so only
these two remain.

Every column is added with a server default, because they are written by raw
INSERTs rather than through the ORM: `default=` in migration 001 is a
client-side SQLAlchemy default and emits no DDL default at all.

Revision ID: 010_outcome_scope_feedback
Revises: 009
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "010_outcome_scope_feedback"
down_revision = "009"
branch_labels = None
depends_on = None

#: Scope and telemetry identifiers, all NOT NULL DEFAULT '' so a raw INSERT
#: that omits them still lands and an absent scope reads as "unscoped" rather
#: than NULL — which would silently drop rows from an `= $n` predicate.
_TEXT_COLUMNS = ("project_id", "dag_id", "dag_run_id", "node_id", "thumb", "thumb_comment")


def upgrade() -> None:
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
