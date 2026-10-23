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

The DDL is guarded (``ADD COLUMN IF NOT EXISTS`` / ``CREATE UNIQUE INDEX IF
NOT EXISTS``), matching the runtime stores' own DDL and the adoption rule
044 states for the chain: a database that already carries the column -- a
schema stamped back and re-upgraded, or a live deployment repaired by hand
-- is adopted untouched instead of failing on ``DuplicateColumn``, and a
fresh database is built to exactly the same definition.
"""

from __future__ import annotations

from alembic import op

revision = "045"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE capability_invocations "
        "ADD COLUMN IF NOT EXISTS logical_effect BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_capability_invocation_active_logical_effect
           ON capability_invocations (run_id, binding_id, effect_key)
           WHERE status IN ('created', 'running', 'unknown') AND logical_effect"""
    )


def downgrade() -> None:
    op.drop_index(
        "uq_capability_invocation_active_logical_effect", table_name="capability_invocations"
    )
    op.drop_column("capability_invocations", "logical_effect")
