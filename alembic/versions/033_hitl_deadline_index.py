"""Index durable HITL deadlines for fair bounded expiry scans (#1056).

Revision ID: 033
Revises: 032
Create Date: 2026-09-07
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
        sa.Column("hitl_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_graph_continuations_hitl_deadline",
        "graph_continuations",
        ["status", "hitl_deadline_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_graph_continuations_hitl_deadline", table_name="graph_continuations")
    op.drop_column("graph_continuations", "hitl_deadline_at")
