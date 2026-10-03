"""Learning validation provenance: the Gauntlet's audit trail (M4-B2).

A learning promoted for collective reuse now carries the evidence that
justified it: the exact canonical Runs of its independent evaluation, the
evaluator's version, when it was validated, and the content hash of the frozen
candidate the evaluation judged. Without the columns, a restart would strip a
promoted learning of its justification and nothing could audit why a row is in
the repertoire.

Defaults rather than nullable columns: a pre-Gauntlet row's absence of
validation is a *known* fact — it was never validated — so `''`/`0`/`'[]'` are
the honest values, unlike producer provenance where NULL preserves "no
execution was in scope".

Revision ID: 051
Revises: 050
Create Date: 2026-10-01

Renumbered 048 -> 051 during the develop integration: while this branch was
open, develop's `048_canvas_job_retry_backoff` (#398) claimed the numeric slot
(and `049_canonical_run_eval_scores` #792 and `050_design_creative_briefs`
#774 chained onto it), which left the tree with a duplicate "048" and two
heads. Re-parenting onto develop's chain tip 050 keeps exactly one linear
head; a string-suffixed id like `048_learning_validation_provenance` was
rejected because it exceeds alembic's 32-character
`alembic_version.version_num` limit (see 041_quota_invocation_evidence).
"""

from __future__ import annotations

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, like 046/047: stamp-back and re-upgrade is a live repair
    # path, and the chain's contract is that re-applying a revision over the
    # schema it already built is adoption, not an error.
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS validated_by TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS "
        "validated_evaluator_version TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS "
        "validated_at DOUBLE PRECISION NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS "
        "validation_run_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS "
        "validation_content_hash TEXT NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    # Dropping these loses the audit trail of why a promoted learning is in
    # the repertoire. The rows keep their promoted status, so knowledge
    # promoted before the downgrade is not demoted by it — the columns record
    # justification, not permission.
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validation_content_hash")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validation_run_ids")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validated_at")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validated_evaluator_version")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validated_by")
