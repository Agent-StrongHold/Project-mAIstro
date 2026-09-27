"""Realign the capability Invocation effect index with the replay contract (#1194).

``SqliteInvocationStore`` dropped ``node_run_id`` from
``idx_capability_invocation_effect`` when ``InvocationStore.list_effect``
widened to ``node_run_id: str | None``: the logical-effect lookup (one
history per Run across every physical NodeRun) and the physical-visit
lookup must both be served by one index. PostgreSQL kept the old shape,
so the two durable backends of one contract drifted. This recreates the
PostgreSQL index in the SQLite shape; admission uniqueness is unaffected
(``uq_capability_invocation_active_effect`` keeps ``node_run_id``).

Renumbered from 042 after the #1120 merge: develop's manual-fire
occurrence migration took the id 042 while this branch was open, so this
revision re-parents onto it to keep the chain single-headed — the same
renumbering this chain has done every time develop took a parent id.
The develop merge then forked the chain again: #1204's
``039_quota_usage_event_identity`` (also a child of 042) landed while this
branch was open, so this revision follows it instead — keeping one linear
head, the same reconciliation this chain's other re-parented revisions
document. Only the parent changes; the DDL is untouched.
"""

from __future__ import annotations

from alembic import op

revision = "043"
down_revision = "039_quota_usage_event_identity"
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
