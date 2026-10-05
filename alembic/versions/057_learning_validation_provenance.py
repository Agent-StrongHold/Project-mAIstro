"""Learning validation provenance: the Gauntlet's audit trail (M4-B2).

A learning promoted for collective reuse now carries the evidence that
justified it: the exact canonical Runs of its independent evaluation, the
evaluator's version, and the content hash of the frozen candidate the
evaluation judged. Without the columns, a restart would strip a promoted
learning of its justification and nothing could audit why a row is in the
repertoire.

Defaults rather than nullable columns: a pre-Gauntlet row's absence of
validation is a *known* fact — it was never validated — so `''`/`'[]'` are
the honest values, unlike producer provenance where NULL preserves "no
execution was in scope". The validator identity (`validated_by`) and the
validation instant (`validated_at`) belong to the ladder revisions this
chain already applied (`052_learning_stage_ladder`, `053_learning_lifecycle_
columns`): they are the transition's actor and instant, shared with the
Gauntlet's audit trail, so this revision adds only what is exclusively the
Gauntlet's — the evaluator build, the evaluation Runs, the frozen content.

Revision ID: 057
Revises: 056
Create Date: 2026-10-01

Renumbered four times during develop integrations. First 048 -> 051: while
this branch was open, develop's `048_canvas_job_retry_backoff` (#398) claimed
the numeric slot (and `049_canonical_run_eval_scores` #792 and
`050_design_creative_briefs` #774 chained onto it), which left the tree with
a duplicate "048" and two heads; re-parenting onto that chain tip 050 kept
exactly one linear head. Then 051 -> 052: the M4-A6 integration renumbered
#792's eval-score evidence onto this branch's old 051 slot (parented on the
same 050, after #780's `049_design_artifact_versions` claimed 049 and pushed
#774's briefs to 050), which left two revisions both named "051" on parent
"050" — two heads again. This revision followed the merged chain tip 051.
Then 052 -> 053: the M4-B1 integration (ADR-103 knowledge-stage ladder) took
"052" on the same parent 051; this revision re-parented onto that ladder tip,
keeping exactly one linear head 053. Then 053 -> 054: develop's M4-B5
(#1753, ADR-100126-8c2d) landed `053_learning_lifecycle_columns` on the same
052 parent, so this revision re-parented onto that lifecycle tip. Now
054 -> 057 in one step: develop went on to claim `054`
(`054_learning_applicability_epistemics`, M4-B3), `055`
(`055_task_admission_generations`), `043_invocation_quota_door` on 055, and
`056` (`056_user_model_facts`) on the quota door, so this revision re-parents
onto develop's tip `056` as `057_learning_validation_provenance`, keeping
exactly one linear head. A string-suffixed id like
`057_learning_validation_provenance` remains rejected: it exceeds alembic's
32-character `alembic_version.version_num` limit (see
041_quota_invocation_evidence).
"""

from __future__ import annotations

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, like 046/047: stamp-back and re-upgrade is a live repair
    # path, and the chain's contract is that re-applying a revision over the
    # schema it already built is adoption, not an error.
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS "
        "validated_evaluator_version TEXT NOT NULL DEFAULT ''"
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
    # justification, not permission. Only this revision's own columns:
    # `validated_by`/`validated_at` belong to 052/053 and must survive a
    # downgrade back to them.
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validation_content_hash")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validation_run_ids")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validated_evaluator_version")
