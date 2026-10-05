"""Learning lifecycle + epistemics columns (M4-B / ADR-100126-8c2d).

The `learnings` table gains the pipeline state the in-memory store already
carries on the row beyond develop's `052_learning_stage_ladder` (which added
the stage rungs and the validation/promotion actors): epistemic type,
confidence with its decay clock, applicability constraints,
reinforcement/contradiction counters, the Gauntlet validation instant, and
the supersession links. A restart must not demote a validated learning back
to a local belief or resurrect a superseded one, so this state is durable
like every other field (#1156's disposition contract now enforces exactly
that).

`created_at` already exists (migration 001) and is now written explicitly by
the stores rather than left to the server default.

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


def upgrade() -> None:
    # IF NOT EXISTS, like 046/047: stamp-back and re-upgrade is a live repair
    # path, and the chain's contract is that re-applying a revision over the
    # schema it already built is adoption, not an error.
    # Develop's 052_learning_stage_ladder added `stage`/`validated_by` with the
    # bottom-rung defaults; this revision extends the same column set with the
    # pipeline epistemics (#117/#121) and the promotion actor, and re-parents
    # onto develop's revision after the 052 collision.
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS epistemic_type "
        "TEXT NOT NULL DEFAULT 'empirical'"
    )
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS confidence "
        "DOUBLE PRECISION NOT NULL DEFAULT 0.5"
    )
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS applicability "
        "JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS reinforcement_count "
        "INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS contradiction_count "
        "INTEGER NOT NULL DEFAULT 0"
    )
    # Instants and supersession links stay nullable: a row written before this
    # revision genuinely has none, and fabricating one would lie about when
    # knowledge was confirmed or replaced.
    op.execute("ALTER TABLE learnings ADD COLUMN IF NOT EXISTS last_confirmed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE learnings ADD COLUMN IF NOT EXISTS validated_at TIMESTAMPTZ")
    op.execute("ALTER TABLE learnings ADD COLUMN IF NOT EXISTS supersedes BIGINT")
    op.execute("ALTER TABLE learnings ADD COLUMN IF NOT EXISTS superseded_by BIGINT")


def downgrade() -> None:
    # Only what this revision added: `stage`, `validated_by` and `promoted_by`
    # belong to develop's `052_learning_stage_ladder` and must survive a
    # downgrade back to it.
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS superseded_by")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS supersedes")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS validated_at")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS last_confirmed_at")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS contradiction_count")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS reinforcement_count")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS applicability")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS confidence")
    op.execute("ALTER TABLE learnings DROP COLUMN IF EXISTS epistemic_type")
