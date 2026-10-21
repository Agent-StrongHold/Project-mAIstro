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

Revision ID: 047
Revises: 046
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_run_eval_scores",
        sa.Column("eval_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("node_run_id", sa.Text, nullable=False),
        sa.Column("attempt_id", sa.Text, nullable=False),
        sa.Column("scored_at", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["canonical_runs.run_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["node_run_id"], ["canonical_node_runs.node_run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["canonical_attempts.attempt_id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_canonical_run_eval_scores_run",
        "canonical_run_eval_scores",
        ["run_id", "scored_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_run_eval_scores_run", table_name="canonical_run_eval_scores")
    op.drop_table("canonical_run_eval_scores")
