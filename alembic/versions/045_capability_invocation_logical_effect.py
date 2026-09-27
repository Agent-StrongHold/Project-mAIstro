"""Run-scoped admission identity for logical capability effects (#1194).

``InvocationExecutionService.invoke(logical_effect=True)`` widened its
history lookup across NodeRuns, but the atomic admission guard -- the
``uq_capability_invocation_active_effect`` partial unique index -- still
keyed on ``(run_id, node_run_id, binding_id, effect_key)``. Two workers
executing the same logical effect concurrently (a harness retry whose lease
loss minted a new NodeRun) both passed admission and both dispatched the
remote side effect: dispatches=2, invocations=2.

The discriminator is now persisted on the row. ``logical_effect`` records
that this Invocation is one effect for the whole Run, and a second partial
unique index -- identical on SQLite, PostgreSQL, and
``SqliteInvocationStore``/``PgInvocationStore`` runtime DDL -- enforces
Run-scoped admission ``(run_id, binding_id, effect_key)`` for exactly those
rows. Physical per-NodeRun admission is unchanged.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "045"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "capability_invocations",
        sa.Column("logical_effect", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_capability_invocation_active_logical_effect
           ON capability_invocations (run_id, binding_id, effect_key)
           WHERE status IN ('created', 'running', 'unknown') AND logical_effect"""
    )


def downgrade() -> None:
    op.drop_index(
        "uq_capability_invocation_active_logical_effect", table_name="capability_invocations"
    )
    op.drop_column("capability_invocations", "logical_effect")
