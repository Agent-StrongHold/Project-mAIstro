"""Learning knowledge-stage ladder: stage columns + append-only transition ledger.

M4-B1 (ADR-103) formalizes the semantic path from local execution memory to
reusable institutional knowledge on the one ``Learning`` record:

    MEMORY -> LEARNING -> VALIDATED -> REPERTOIRE

- ``stage`` is the ladder position (default ``memory`` — every pre-ladder row
  lands on the bottom rung; the upgrade fabricates no validation or promotion
  that never happened, and blank ``validated_by``/``promoted_by`` stay blank).
- ``status`` is unchanged and remains the read surface: ``promoted``-only
  readers keep working. A REPERTOIRE commit flips ``status`` itself.
- ``learning_stage_transitions`` is the append-only audit trail: one row per
  accepted transition, written in the same transaction as the row update, so
  provenance is durable and auditable rather than recoverable after the fact.

Numbered 048 when written; develop's #398 took that id first
(`048_canvas_job_retry_backoff`), so per this chain's collision convention the
revision re-parents onto it as 049 — the same renumbering 039/043/045 went
through. One linear head, no duplicate revision ids.

Revision ID: 049
Revises: 048
Create Date: 2026-10-01
"""

from __future__ import annotations

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None

_STAGE_COLUMNS = (
    "stage TEXT NOT NULL DEFAULT 'memory'",
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
    op.execute("DROP TABLE IF EXISTS learning_stage_transitions")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS promoted_by")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validated_by")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS stage")
