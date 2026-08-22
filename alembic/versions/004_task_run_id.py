"""Correlate durable task receipts with their canonical Run (#41).

Every task admitted through the queue now creates a Run over a one-node Graph,
and the Run is the execution identity. The persisted TaskRecord is the receipt;
without this column a restart can read back a task but cannot find the Run that
is actually executing it, which is the correlation #41 requires.

Nullable on purpose: rows written before this migration have no Run, and a task
submitted through a build with no Run store wired still writes a receipt.

Revision ID: 004
Revises: 003
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("run_id", sa.String(64), nullable=True))
    op.create_index("ix_tasks_run_id", "tasks", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_run_id", table_name="tasks")
    op.drop_column("tasks", "run_id")
