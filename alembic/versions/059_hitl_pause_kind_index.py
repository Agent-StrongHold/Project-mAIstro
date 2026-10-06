"""Index the pause-kind projection for fair pending HITL discovery (#1109).

Pending human discovery previously paged the generic PAUSED listing and
filtered each page in memory, so ``limit`` bounded a PAUSED *prefix* rather
than human work: more machine-only pauses than the scan could inspect hid the
human pause behind them from every request, permanently. The pause-kind column
is the same kind of lookup projection as ``hitl_deadline_at`` (034) — it makes
human eligibility selectable before LIMIT, without becoming a second HITL
queue: the canonical pause entry stays the authority and every disclosed item
is revalidated against it at read time.

Revision ID: 059
Revises: 058
Create Date: 2026-10-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "graph_continuations",
        sa.Column(
            "has_hitl_pause",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # The pause entry remains authoritative; this projection only makes human
    # eligibility selectable without reading a bounded PAUSED prefix first.
    #
    # Backfilled from the continuation JSON with the runtime's own policy
    # (`has_active_hitl_pause`): an active frontier node whose durable pause
    # entry declares kind = 'hitl'. A row whose JSON cannot be interpreted
    # stays FALSE -- unindexed, exactly as the runtime leaves a non-human
    # pause -- and the pause entry itself is untouched. Pending discovery
    # revalidates every disclosed record against that entry regardless.
    op.execute(
        sa.text(
            """
            UPDATE graph_continuations AS gc
               SET has_hitl_pause = EXISTS (
                     SELECT 1
                       FROM jsonb_array_elements_text(
                           COALESCE(
                               gc.continuation -> 'graph_state' -> 'active_node_ids',
                               '[]'::jsonb
                           )
                       ) AS active(node_id)
                      WHERE gc.continuation -> 'graph_state' -> 'metadata'
                            -> 'pauses' -> active.node_id ->> 'kind' = 'hitl'
                   )
            """
        )
    )
    op.create_index(
        "ix_graph_continuations_hitl_paused",
        "graph_continuations",
        ["status", "has_hitl_pause", "created_at", "run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_graph_continuations_hitl_paused", table_name="graph_continuations")
    op.drop_column("graph_continuations", "has_hitl_pause")
