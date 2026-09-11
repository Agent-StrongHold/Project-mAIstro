"""Index durable HITL deadlines for fair bounded expiry scans (#1056).

The column is a lookup projection, so upgrading must populate it from the
canonical pause entries already stored in each continuation. Leaving old rows
NULL would make those pauses permanently invisible to the bounded expiry scan.

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
    # The pause entry remains authoritative; this projection only makes the
    # existing durable facts selectable without a global PAUSED-prefix scan.
    op.execute(
        sa.text(
            """
            UPDATE graph_continuations AS gc
               SET hitl_deadline_at = due.deadline_at
              FROM (
                    SELECT existing.run_id,
                           MIN((pause.value ->> 'resume_at')::timestamptz) AS deadline_at
                      FROM graph_continuations AS existing
                      CROSS JOIN LATERAL jsonb_array_elements_text(
                          COALESCE(
                              existing.continuation -> 'graph_state' -> 'active_node_ids',
                              '[]'::jsonb
                          )
                      ) AS active(node_id)
                      JOIN LATERAL jsonb_each(
                          COALESCE(
                              existing.continuation -> 'graph_state' -> 'metadata' -> 'pauses',
                              '{}'::jsonb
                          )
                      ) AS pause(node_id, value) ON pause.node_id = active.node_id
                     WHERE existing.status = 'paused'
                       AND pause.value ->> 'kind' = 'hitl'
                       AND pause.value ->> 'resume_at' IS NOT NULL
                     GROUP BY existing.run_id
                   ) AS due
             WHERE gc.run_id = due.run_id
            """
        )
    )
    op.create_index(
        "ix_graph_continuations_hitl_deadline",
        "graph_continuations",
        ["status", "hitl_deadline_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_graph_continuations_hitl_deadline", table_name="graph_continuations")
    op.drop_column("graph_continuations", "hitl_deadline_at")
