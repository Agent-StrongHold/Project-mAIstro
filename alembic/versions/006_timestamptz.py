"""Timezone-aware timestamps, so time-filtered queries can run at all (#122).

Migration 001 declared every timestamp as `sa.DateTime` — PostgreSQL
`TIMESTAMP WITHOUT TIME ZONE`. The stores that query them compute their cutoffs
as `datetime.now(UTC) - timedelta(...)`, which is *aware*. asyncpg refuses the
combination outright:

    asyncpg.exceptions.DataError: invalid input for query argument $1:
    datetime.datetime(...) (can't subtract offset-naive and offset-aware
    datetimes)

That is not a corner case. It is every time-filtered method on
`PgOutcomeStore` — `list_outcomes`, `get_task_completion_rate`,
`get_usage_breakdown`, `get_daily_timeseries`, `get_experience_context` — none
of which could execute. Nothing noticed because nothing wired the PostgreSQL
stores (#122) and their tests mocked the connection, so the SQL was asserted and
never run.

Aware is the correct direction rather than merely the convenient one: a naive
column in a durable store means the value's meaning depends on the writer's
locale, and this project already moved its schedule model to aware datetimes for
the same reason. Migration 005 uses `TIMESTAMPTZ` throughout, so 001's columns
are now the outlier.

Existing values are converted with `AT TIME ZONE 'UTC'`, which is what they
already were — `memory/store.py` stored "UTC wall-clock values" into these
columns deliberately, and the task queue had a `_naive()` helper whose whole job
was stripping the tzinfo on the way in. That helper goes away with this.

Revision ID: 006
Revises: 005
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

#: Every naive timestamp column created by migration 001.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("tasks", "created_at"),
    ("tasks", "started_at"),
    ("tasks", "completed_at"),
    ("memory_entries", "created_at"),
    ("knowledge_nodes", "updated_at"),
    ("learnings", "created_at"),
    ("episodic_memories", "created_at"),
    ("episodic_memories", "last_accessed_at"),
    ("outcomes", "created_at"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
