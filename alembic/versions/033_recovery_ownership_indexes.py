"""Index durable recovery candidates by their admission owner (#1098).

Revision ID: 033
Revises: 032
Create Date: 2026-09-07

Recovery ownership is durable Run provenance. These denormalized columns let
both recovery projections apply the owner predicate before LIMIT; nullable
values preserve the explicit compatibility disposition for historical rows
that never declared an admission source.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "graph_continuations",
        sa.Column("admission_source", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_graph_continuations_status_owner",
        "graph_continuations",
        ["status", "admission_source", "created_at"],
    )
    op.create_index(
        "ix_graph_continuations_due_owner",
        "graph_continuations",
        ["admission_source", "resume_at", "run_id"],
        postgresql_where=sa.text("resume_at IS NOT NULL"),
    )
    # Backfill only from canonical facts. A missing/non-string source remains
    # NULL and is therefore never silently assigned to a recovery consumer
    # using an owner-specific query.
    op.execute(
        sa.text(
            """UPDATE graph_continuations AS gc
               SET admission_source = cr.payload->'provenance'->>'admission_source'
              FROM canonical_runs AS cr
             WHERE cr.run_id = gc.run_id
               AND jsonb_typeof(cr.payload->'provenance'->'admission_source') = 'string'"""
        )
    )
    op.add_column(
        "canonical_runs",
        sa.Column("admission_source", sa.Text, nullable=True),
    )
    op.execute(
        sa.text(
            """UPDATE canonical_runs
               SET admission_source = payload->'provenance'->>'admission_source'
             WHERE jsonb_typeof(payload->'provenance'->'admission_source') = 'string'"""
        )
    )
    op.create_index(
        "ix_canonical_runs_status_owner",
        "canonical_runs",
        ["status", "admission_source", "run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_runs_status_owner", table_name="canonical_runs")
    op.drop_column("canonical_runs", "admission_source")
    op.drop_index("ix_graph_continuations_due_owner", table_name="graph_continuations")
    op.drop_index("ix_graph_continuations_status_owner", table_name="graph_continuations")
    op.drop_column("graph_continuations", "admission_source")
