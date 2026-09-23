"""Realign the capability Invocation effect index with the replay contract (#1194).

``SqliteInvocationStore`` dropped ``node_run_id`` from
``idx_capability_invocation_effect`` when ``InvocationStore.list_effect``
widened to ``node_run_id: str | None``: the logical-effect lookup (one
history per Run across every physical NodeRun) and the physical-visit
lookup must both be served by one index. PostgreSQL kept the old shape,
so the two durable backends of one contract drifted. This recreates the
PostgreSQL index in the SQLite shape; admission uniqueness is unaffected
(``uq_capability_invocation_active_effect`` keeps ``node_run_id``).
"""

from __future__ import annotations

from alembic import op

revision = "042"
down_revision = "036_audit_log_org_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_capability_invocation_effect", table_name="capability_invocations")
    op.create_index(
        "idx_capability_invocation_effect",
        "capability_invocations",
        ["run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_capability_invocation_effect", table_name="capability_invocations")
    op.create_index(
        "idx_capability_invocation_effect",
        "capability_invocations",
        ["run_id", "node_run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
    )
