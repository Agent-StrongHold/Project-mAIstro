"""Durable tables for the canonical Workspace BacklogItem work-source (#82).

Attaches after develop's trunk chain tip, `043_invocation_quota_door`
(#1196/#718, itself continuing `055_task_admission_generations`, which
follows `054_learning_applicability_epistemics` and
`053_learning_lifecycle_columns`) per the convention 046 records: the
branch's original `048`/`049` slots were renumbered after develop landed its
own `048` (and later `049`-`051`), then onto `054`/`055` after develop
claimed `052` (`052_learning_stage_ladder`, ADR-103) and `053`
(`053_learning_lifecycle_columns`), then onto `056`/`057` after develop
claimed `054` (M4-B3, #119) and `055` (#1892) and re-parented its quota door
onto that tip, then onto `058`/`059` after develop's trunk landed
`056_user_model_facts` (#1047) on the same quota-door parent with #863's
planner-stability revision on top as `057_run_store_planner_stability`, and
now onto `059`/`060` after develop's Gauntlet provenance ledger (#118,
M4-B2) landed on that tip as `058_learning_validation_provenance`. Because a
landed trunk migration never moves, the branch-side pair re-parents past the
incoming develop tip — the numbering tracks the chain, not the issue number,
so the chain stays linear with exactly one head.

The DDL is guarded (`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT
EXISTS`), matching the SQLite twin's `ensure_schema`
(`maistro.backlog.sqlite_store`) and the chain's re-application contract: a
database that already carries these tables is adopted untouched; a fresh one
is built to exactly the definition the runtime store reads
(`maistro.backlog.pg_store`). BacklogItems hold Workspace work-source state,
so the tables are tenanted by `workspace_id` and the claim/event rows
reference their item.

`backlog_events.seq` is the per-database append order provenance (#101) is
read in; `backlog_claims` holds one row per item -- the current claim, active
or released -- while the event log keeps the full claim history.
"""

from __future__ import annotations

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backlog_items (
            item_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            parent_id TEXT,
            status TEXT NOT NULL,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL,
            payload JSONB NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_backlog_items_workspace "
        "ON backlog_items (workspace_id, status)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_backlog_items_children ON backlog_items (parent_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backlog_claims (
            item_id TEXT PRIMARY KEY REFERENCES backlog_items (item_id),
            claim_id TEXT NOT NULL,
            claimed_by TEXT NOT NULL,
            claimed_at TIMESTAMPTZ NOT NULL,
            lease_expires_at TIMESTAMPTZ NOT NULL,
            released_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backlog_events (
            seq BIGSERIAL PRIMARY KEY,
            event_id TEXT NOT NULL,
            item_id TEXT NOT NULL REFERENCES backlog_items (item_id),
            at TIMESTAMPTZ NOT NULL,
            actor TEXT NOT NULL,
            kind TEXT NOT NULL,
            item_version INTEGER NOT NULL,
            payload JSONB NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_backlog_events_item ON backlog_events (item_id, seq)"
    )


def downgrade() -> None:
    op.drop_index("idx_backlog_events_item", table_name="backlog_events")
    op.drop_table("backlog_events")
    op.drop_table("backlog_claims")
    op.drop_index("idx_backlog_items_children", table_name="backlog_items")
    op.drop_index("idx_backlog_items_workspace", table_name="backlog_items")
    op.drop_table("backlog_items")
