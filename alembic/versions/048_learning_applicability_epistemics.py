"""Learnings carry applicability, measured confidence, evidence and epistemic type (M4-B3).

A reusable learning used to be one string plus counters. Nothing on the record
said where the claim holds (`works_when`), where it must not be applied
(`avoid_in`), how strong the evidence behind it is (`confidence`), which Runs or
evaluations supplied that evidence, or whether the claim was measured,
inferred, counterfactual or imported. Two consequences: retrieval could not
order a tested correction above a plausible-sounding one, and promotion keyed
on hit_count alone — a claim promoted for being *retrieved often* rather than
for being *right*.

Column dispositions follow the record's own semantics:

- `confidence` is the only nullable column. NULL means "never measured", and
  promotion treats that as a blocker; a `NOT NULL DEFAULT 0.0` would have made
  every legacy row read as measured-and-failing, and a 1.0 default as
  measured-and-perfect. Both fabricate evidence (the rule ADR-083026-a91e set
  for metrics: absent is not zero).
- The JSONB applicability/evidence columns default to `'[]'` and
  `epistemic_type` to `'observed'` — the honest reading of every pre-M4-B3 row,
  which was observed-by-construction and had no applicability recorded.
- `evidence_run_ids` is a list alongside the scalar `run_id` from migration 026:
  `run_id` names the one Run that produced the text, the list names every Run
  whose outcome supports the claim, and consolidation/rewording merges rows
  while supporting executions accumulate. Provenance must survive the merge.

The SQLite twin upgrades existing files in place (`ensure_schema`); this
migration is the PostgreSQL half of the same shape.

Revision ID: 048
Revises: 047
Create Date: 2026-10-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("epistemic_type", sa.Text(), "'observed'"),
    # Same column kind as `trigger_keys` from migration 001: the stores write
    # `json.dumps` text and asyncpg lets the server infer the JSONB target.
    ("works_when", postgresql.JSONB(), "'[]'::jsonb"),
    ("avoid_in", postgresql.JSONB(), "'[]'::jsonb"),
    ("confidence", sa.Float(), None),
    ("evidence_run_ids", postgresql.JSONB(), "'[]'::jsonb"),
    ("evaluation_ids", postgresql.JSONB(), "'[]'::jsonb"),
)


def upgrade() -> None:
    for name, column_type, default in _COLUMNS:
        op.add_column(
            "learnings",
            sa.Column(
                name,
                column_type,
                nullable=default is not None,
                server_default=default,
            ),
        )
    # Promotion now asks "which rows may promote" across applicability and
    # confidence; this index serves the candidate scan the same way
    # idx_learnings_scope serves the scope-filtered reads.
    op.create_index(
        "idx_learnings_promotion_candidates",
        "learnings",
        ["org_id", "status", "hit_count"],
    )


def downgrade() -> None:
    op.drop_index("idx_learnings_promotion_candidates", table_name="learnings")
    for name, _column_type, _default in reversed(_COLUMNS):
        op.drop_column("learnings", name)
