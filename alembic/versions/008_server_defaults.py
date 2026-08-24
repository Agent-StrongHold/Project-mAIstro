"""Make migration 001's declared defaults exist in the database (#122).

Migration 001 writes columns as `nullable=False, default=...`. In SQLAlchemy
`default=` is a **client-side** default: it applies when the ORM builds the
INSERT, and it is absent from the DDL entirely. Every one of these columns was
therefore created `NOT NULL` with no default at all — and the stores that write
these tables use raw asyncpg, not the ORM, so nothing ever supplied the value
the migration appeared to promise.

The first insert through `PgOutcomeStore.record` fails on it:

    asyncpg.exceptions.NotNullViolationError: null value in column "org_id" of
    relation "outcomes" violates not-null constraint

`server_default=` is what 001 meant. Adding it is idempotent for existing rows —
the constraint already guaranteed every stored row has a value — and turns a
column the code may legitimately omit from an INSERT into one the database can
fill, rather than a 500 on the write path.

This does not paper over a store that *should* be writing a column: #122 also
fixes `PgOutcomeStore.record` to persist `org_id`, without which every
org-scoped query filters on a value that was never stored. The two are
complementary — one makes omission survivable, the other stops the omission that
mattered.

Revision ID: 008
Revises: 007
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

#: (table, column, SQL default) for every `nullable=False, default=...` column
#: migration 001 declared. Values mirror that file exactly.
_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    ("learnings", "category", "'general'"),
    ("learnings", "org_id", "''"),
    ("learnings", "team_id", "''"),
    ("learnings", "scope", "'agent'"),
    ("learnings", "hit_count", "0"),
    ("learnings", "status", "'active'"),
    ("episodic_memories", "weight", "0.3"),
    ("episodic_memories", "org_id", "''"),
    ("episodic_memories", "team_id", "''"),
    ("episodic_memories", "scope", "'agent'"),
    ("episodic_memories", "source", "''"),
    ("episodic_memories", "reinforcement_count", "0"),
    ("episodic_memories", "contradiction_count", "0"),
    ("episodic_memories", "deleted", "FALSE"),
    ("outcomes", "task_type", "''"),
    ("outcomes", "model_used", "''"),
    ("outcomes", "provider", "''"),
    ("outcomes", "success", "TRUE"),
    ("outcomes", "error_type", "''"),
    ("outcomes", "response_time_ms", "0"),
    ("outcomes", "org_id", "''"),
    ("outcomes", "team_id", "''"),
    ("outcomes", "user_id", "''"),
    ("outcomes", "input_tokens", "0"),
    ("outcomes", "output_tokens", "0"),
)


def upgrade() -> None:
    for table, column, default in _DEFAULTS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default}")


def downgrade() -> None:
    for table, column, _default in _DEFAULTS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
