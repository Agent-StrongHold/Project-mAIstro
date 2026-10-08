"""Index the pause-kind projection for fair pending HITL discovery (#1109).

Pending human discovery previously paged the generic PAUSED listing and
filtered each page in memory, so ``limit`` bounded a PAUSED *prefix* rather
than human work: more machine-only pauses than the scan could inspect hid the
human pause behind them from every request, permanently. The pause-kind column
is the same kind of lookup projection as ``hitl_deadline_at`` (034) — it makes
human eligibility selectable before LIMIT, without becoming a second HITL
queue: the canonical pause entry stays the authority and every disclosed item
is revalidated against it at read time.

Revision ID: 061
Revises: 060
Create Date: 2026-10-06

Renumbered once during a develop integration: written as `059` on the
`058` tip, the sync landed develop's backlog pair (#98/#102) on that same
tip as `059_backlog_work_source` and `060_backlog_authority_cutover` —
and a landed trunk migration never moves. This revision therefore
re-parents onto develop's `060` and takes the next free slot, keeping the
chain linear with exactly one head (046 records the convention, 058 the
nearest precedent).

The DDL is guarded (``ADD COLUMN IF NOT EXISTS`` / ``CREATE INDEX IF NOT
EXISTS``), matching the runtime stores' own DDL and the adoption rule 044
states for the chain: re-applying the chain over a schema that already
carries the projection -- stamped back and re-upgraded, the repair path
tests/migrations/test_migration_chain.py pins -- must adopt it untouched
instead of failing on ``DuplicateColumn`` (#1194's 045 made the same point
for the same reason). Re-running the backfill is safe by construction: it
recomputes the projection from the canonical pause entries with the
runtime's own policy, so it lands on the values the store maintains anyway.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE graph_continuations "
        "ADD COLUMN IF NOT EXISTS has_hitl_pause BOOLEAN NOT NULL DEFAULT FALSE"
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
    op.execute(
        """CREATE INDEX IF NOT EXISTS ix_graph_continuations_hitl_paused
           ON graph_continuations (status, has_hitl_pause, created_at, run_id)"""
    )


def downgrade() -> None:
    op.drop_index("ix_graph_continuations_hitl_paused", table_name="graph_continuations")
    op.drop_column("graph_continuations", "has_hitl_pause")
