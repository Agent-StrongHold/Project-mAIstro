"""Graph continuations beside the canonical spine (#44).

Durable Graph execution kept the canonical Run, its NodeRuns and its Attempts
inside one aggregate document in a store of its own, so a graph Run was
invisible to every canonical consumer — `GET /v1/runs/{id}` could not find it,
and the lease sweep and retention policy could not see its work. The spine now
holds those three entities, and this table holds what is genuinely left over:
the frontier, blackboard, routing decisions and commit history that ADR-062
keeps in `GraphExecutionState` precisely because traversal state is not
execution lifecycle.

`status`, `project_id` and `created_at` are denormalized from the canonical
Run so a "which graph runs are paused" query is an index scan rather than a
walk of every Run. The Run remains the authority; assembly reads the status
back from it.

`version` carries the same optimistic-concurrency envelope the durable store
had, because two workers resuming one paused Run is exactly the race it
existed to lose safely.

Revision ID: 021
Revises: 020
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_continuations",
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("project_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resume_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("continuation", postgresql.JSONB, nullable=False),
        sa.PrimaryKeyConstraint("run_id", name="pk_graph_continuations"),
        sa.CheckConstraint("version >= 0", name="ck_graph_continuations_version"),
    )
    op.create_index(
        "ix_graph_continuations_status", "graph_continuations", ["status", "project_id"]
    )
    op.create_index(
        "ix_graph_continuations_project", "graph_continuations", ["project_id", "created_at"]
    )
    op.create_index("ix_graph_continuations_resume_at", "graph_continuations", ["resume_at"])


def downgrade() -> None:
    op.drop_index("ix_graph_continuations_resume_at", table_name="graph_continuations")
    op.drop_index("ix_graph_continuations_project", table_name="graph_continuations")
    op.drop_index("ix_graph_continuations_status", table_name="graph_continuations")
    op.drop_table("graph_continuations")
