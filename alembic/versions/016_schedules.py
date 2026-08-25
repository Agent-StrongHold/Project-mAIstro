"""Durable Schedule definitions and fire cursors (#231).

`ScheduleStore` has had three implementations since #145 — in-memory, SQLite,
and the protocol — and no PostgreSQL one, which meant the canonical store the
`ScheduleRunAdmitter` writes its cursor into could not be shared between two
processes. That is not a gap the admitter can close: #220 made
`(schedule_id, scheduled_for)` a durable occurrence claim so concurrent tickers
cannot both create a Run for one occurrence, and a claim is only worth as much
as the schedule row it advances.

`next_due_at` and `enabled` are lifted out of the payload into columns for the
same reason `SqliteScheduleStore` lifts them: the due query runs on every tick,
and a deserialise-everything sweep grows with every schedule ever created.

`workspace_id` and `project_id` are columns rather than payload keys because
`list_for_project` is the scoped read the product surface issues, and scope is
the axis this table is partitioned along.

Revision ID: 016
Revises: 015
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("schedule_id", sa.Text, nullable=False),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("project_id", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("schedule_id", name="pk_schedules"),
    )
    # The tick's due() query. Partial on `enabled` because a disabled schedule
    # is never due, and an exhausted `max_runs` disables rather than deletes —
    # so the dead rows accumulate and would otherwise stay in the scan.
    op.create_index(
        "ix_schedules_due",
        "schedules",
        ["next_due_at"],
        postgresql_where=sa.text("enabled"),
    )
    op.create_index("ix_schedules_scope", "schedules", ["workspace_id", "project_id"])


def downgrade() -> None:
    op.drop_index("ix_schedules_scope", table_name="schedules")
    op.drop_index("ix_schedules_due", table_name="schedules")
    op.drop_table("schedules")
