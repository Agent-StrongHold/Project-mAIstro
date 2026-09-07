"""Episodic memory names the execution that stored it (#64).

Migration 026 put nullable `run_id`/`node_run_id`/`attempt_id` on `learnings`,
`outcomes` and `design_outputs`, and named `episodic_memories` the exception:
nothing outside `alembic/` wrote the table, so columns there would have been a
durability claim with nothing behind it. #710 then made the episodic stores
durable — `PgEpisodicStore`, `SqliteEpisodicStore`, both wired by the container —
which is the condition 026's docstring named for coming back. This is that
follow-up, the last record kind in #64's first acceptance bullet without a
producer reference.

Nullable, for the same reason 026 gave: rows written before this and writes with
no execution in scope are legitimate, and a `NOT NULL DEFAULT ''` would make
each of them claim a Run whose id is the empty string.

One index, on `run_id` alone, mirroring 026: "what did this execution
remember" is the question these columns exist to answer, and the follow-on
`produced_by(run_id, org_id=...)` narrows from it cheaply.

Revision ID: 031
Revises: 030
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None

_COLUMNS = ("run_id", "node_run_id", "attempt_id")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("episodic_memories", sa.Column(column, sa.Text, nullable=True))
    op.create_index("idx_episodic_memories_run_id", "episodic_memories", ["run_id"])


def downgrade() -> None:
    op.drop_index("idx_episodic_memories_run_id", table_name="episodic_memories")
    for column in _COLUMNS:
        op.drop_column("episodic_memories", column)
