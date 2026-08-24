"""Correlate durable task receipts with their canonical Run (#41).

Every task admitted through the queue now creates a Run over a one-node Graph,
and the Run is the execution identity. The persisted TaskRecord is the receipt;
without this column a restart can read back a task but cannot find the Run that
is actually executing it, which is the correlation #41 requires.

Nullable on purpose: rows written before this migration have no Run, and a task
submitted through a build with no Run store wired still writes a receipt.

Revision ID: 004_task_run_id
Revises: 004_durable_events

Identified by name rather than by the next number. `004` was taken while this
branch was open: #135's durable-event tables landed on `develop` as `004`, and
two revisions sharing an id give alembic multiple heads and an ambiguous parent
for everything after them — a break `git` cannot see, because the two are
different files. The repository already fixed this race for ADRs
(ADR-062026-9b30, which froze sequential `ADR-NNN` for exactly this reason);
a migration id derived from what the migration *does* cannot collide with a
concurrently-open branch either.

Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004_task_run_id"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("run_id", sa.String(64), nullable=True))
    op.create_index("ix_tasks_run_id", "tasks", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_run_id", table_name="tasks")
    op.drop_column("tasks", "run_id")
