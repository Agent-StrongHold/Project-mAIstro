"""Eval scores as durable Run evidence (M7-A3, #792).

Scoring a design artifact is part of the same execution that produced it, so
the score lives on the canonical spine — a `canonical_run_eval_scores` row
names the Run, the NodeRun whose work it scores, and the Attempt whose evidence
it scored, with the same `ON DELETE RESTRICT` foreign keys the spine itself
uses. An eval record can therefore never outlive, or hang off, a spine row
that is gone: no `EvalRun` sidecar, no second execution identity.
Append-only by primary key. A re-evaluation is a new Attempt and a new row;
the failed record stays queryable.

Shape follows migration 012: a JSONB payload holding the whole model, plus the
columns the reads order or join on. Non-finite scores cannot occur — the model
rejects NaN/Infinity — so the payload needs no non-finite tagging beyond what
`maistro.runs.evidence_json` already does for the spine tables.

Revision ID: 051
Revises: 050
Create Date: 2026-09-29
"""

from __future__ import annotations

from alembic import op

# 049 after develop's `048_canvas_job_retry_backoff` (#398) claimed the
# number this branch first took after the earlier `047`
# `capability_binding_revocations` (#1133) collision, then to `051` when the
# auto-780 develop sync collided once more: `049_design_artifact_versions`
# (#780) had already taken `049` on the same parent `048`, with #774's
# `050_design_creative_briefs` continuing it — so the eval evidence
# re-parents onto that `050` as `051`, the same renumbering this chain
# performs on every develop collision so it keeps exactly one linear head.
revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, like 046 and 047: stamp-back and re-upgrade is a live
    # repair path, and the chain's contract is that re-applying a revision
    # over the schema it already built is adoption, not an error
    # (tests/migrations,
    # test_reapplying_the_chain_over_an_already_migrated_schema_is_adopted).
    # A bare create_table failed that with DuplicateTable.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_run_eval_scores (
            eval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_run_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            scored_at TEXT NOT NULL,
            payload JSONB NOT NULL,
            FOREIGN KEY (run_id) REFERENCES canonical_runs (run_id) ON DELETE RESTRICT,
            FOREIGN KEY (node_run_id) REFERENCES canonical_node_runs (node_run_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (attempt_id) REFERENCES canonical_attempts (attempt_id)
                ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_canonical_run_eval_scores_run
            ON canonical_run_eval_scores (run_id, scored_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_canonical_run_eval_scores_run")
    op.execute("DROP TABLE IF EXISTS canonical_run_eval_scores")
