"""Durable tables for the canonical Workspace BacklogItem work-source (#82).

Attaches after the trunk chain tip per the convention 046 records: the
id/parent numbering tracks the chain, not the issue number, so the chain stays
linear with exactly one head. Originally filed as ``048`` alongside develop's
``048_canvas_job_retry_backoff`` -- the same two-head collision #1341 removed --
and renumbered to ``049``; when develop then landed its own ``049``
(``049_canonical_run_eval_scores``) and ``050`` through the 045cfdfbe sync, this
migration re-attached after that tip as ``051`` so the chain again keeps exactly
one head; and when the 829de3dac sync brought develop's renumbered
``051_canonical_run_eval_scores`` (which had re-parented onto develop's own
``050``) onto the same parent this migration had taken, it collided with the
``051`` this branch already held and re-attached after that tip as ``052`` --
the same move one more time; and when the a58656017 sync brought develop's
knowledge-stage ladder -- numbered ``048`` when written, re-parented onto the
same chain tip as ``052_learning_stage_ladder`` (M4-B1, ADR-103) -- it collided
with the ``052`` this migration already held, so it re-attached after that tip
as ``053``, keeping exactly one head. The 56332162c sync then delivered
develop's originals of every revision this branch had been carrying renumbered
-- ``053_learning_lifecycle_columns``, ``054_learning_applicability_epistemics``,
``055_task_admission_generations``, ``056_user_model_facts`` and
``057_run_store_planner_stability`` -- so the branch-side duplicates were dropped
and this migration, the one genuinely-new branch revision left, re-attached
after that ``057`` tip as ``058``. The a8258ee24 sync then delivered develop's
``058_learning_validation_provenance`` (Gauntlet validation provenance, M4-B2
#118) onto the same ``057`` parent, colliding a fourth time, so this migration
re-attached after that ``058`` tip as ``059`` -- keeping exactly one head.

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
