"""Learning knowledge-stage ladder: stage columns + append-only transition ledger.

M4-B1 (ADR-103) formalizes the semantic path from local execution memory to
reusable institutional knowledge on the one ``Learning`` record:

    MEMORY -> LEARNING -> VALIDATED -> REPERTOIRE

- ``stage`` is the ladder position (default ``learning`` — rows enter the
  ladder at the extracted-claim rung per ADR-100126-9a4b, the merged tree's
  implemented semantics; extraction is the MEMORY -> LEARNING step. The
  upgrade fabricates no validation or promotion that never happened, and
  blank ``validated_by``/``promoted_by`` stay blank).
- ``status`` is unchanged and remains the read surface: ``promoted``-only
  readers keep working. A REPERTOIRE commit flips ``status`` itself.
- ``learning_stage_transitions`` is the append-only audit trail: one row per
  accepted transition, written in the same transaction as the row update, so
  provenance is durable and auditable rather than recoverable after the fact.

Numbered 048 when written; develop claimed that id for #398
(`048_canvas_job_retry_backoff`) while the branch that wrote it was open, so
per this chain's collision convention the revision re-parented onto it — and
develop kept colliding while that branch stayed open:
`049_design_artifact_versions` (#780), `050_design_creative_briefs` (#774),
and — re-parented onto that `050` by its own branch's develop sync —
`051_canonical_run_eval_scores` (#792) each took the next id in turn. The
ladder first re-parented onto the `051_canonical_run_eval_scores` chain tip
as 052, but `052_learning_lifecycle_columns` (M4-B, ADR-100126-9a4b) took
that id on the same parent in the same merge that brought this revision over,
so the ladder re-parents once more, as `053` on that column revision. One
linear head, no duplicate revision ids.

Revision ID: 053
Revises: 052
Create Date: 2026-10-01
"""

from __future__ import annotations

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None

_STAGE_COLUMNS = (
    "stage TEXT NOT NULL DEFAULT 'learning'",
    "validated_by TEXT NOT NULL DEFAULT ''",
    "promoted_by TEXT NOT NULL DEFAULT ''",
)


def upgrade() -> None:
    # IF NOT EXISTS / IF NOT EXISTS throughout, like 046/047: re-applying a
    # revision over the schema it already built is adoption, not an error.
    for column in _STAGE_COLUMNS:
        op.execute(f"ALTER TABLE learnings ADD COLUMN IF NOT EXISTS {column}")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_stage_transitions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            learning_id BIGINT NOT NULL,
            org_id TEXT NOT NULL DEFAULT '',
            from_stage TEXT NOT NULL,
            to_stage TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_learning_stage_transitions_learning "
        "ON learning_stage_transitions (learning_id, id)"
    )


def downgrade() -> None:
    # Dropping the ledger loses the audit trail of how claims came to be
    # believed — a downgrade that discards provenance. Kept for chain
    # symmetry, like 047; an operator running it is choosing that.
    #
    # Only this revision's own columns go: `promoted_by`. `stage` and
    # `validated_by` are owned by `052_learning_lifecycle_columns` in the
    # merged chain (this revision's ADD COLUMN IF NOT EXISTS for them is a
    # no-op there), so dropping them here would hand revision 052 a schema
    # missing columns it claims.
    op.execute("DROP TABLE IF EXISTS learning_stage_transitions")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS promoted_by")
