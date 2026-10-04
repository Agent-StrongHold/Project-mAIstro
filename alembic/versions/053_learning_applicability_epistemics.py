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
  The DDL is spelled as raw SQL with `ADD COLUMN IF NOT EXISTS` (migration
  025's idiom): a `server_default` string on `op.add_column` is rendered as a
  *quoted literal* (`DEFAULT '''[]''::jsonb'`, not valid JSON — first boot of
  a clean install died inside `ALTER TABLE`, observed as Gate C's
  `maistro-engine is unhealthy` and formal-conformance's `invalid input
  syntax for type json`), and a bare `ADD COLUMN` is not adoption-safe against
  the stamp-back + re-upgrade repair path the chain is re-applied with.
- `evidence_run_ids` is a list alongside the scalar `run_id` from migration 026:
  `run_id` names the one Run that produced the text, the list names every Run
  whose outcome supports the claim, and consolidation/rewording merges rows
  while supporting executions accumulate. Provenance must survive the merge.

The SQLite twin upgrades existing files in place (`ensure_schema`); this
migration is the PostgreSQL half of the same shape.

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

# Renumbered three times per the chain's standing collision convention (see
# 046's docstring): first from "048" on parent "047" when develop claimed that
# id for `048_canvas_job_retry_backoff` on the same parent, then from "051" on
# parent "050" when the auto-780 develop sync brought
# `051_canonical_run_eval_scores` (#792) onto that same parent, and finally
# from "052" on parent "051" when the auto-119 develop sync brought
# `052_learning_stage_ladder` (M4-B1, ADR-103) onto that same parent. Each
# collision leaves two revisions sharing one id and two heads — `alembic
# history` fails outright on that shape. This migration now attaches after
# develop's chain tip `052` (`learning_stage_ladder`), keeping exactly one
# head.

# Column DDL, in declaration order. The defaults are expression text (the cast
# `'[]'::jsonb` is SQL, not a JSON value), matching what the SQLite twin's
# in-place upgrade writes. `confidence` deliberately has no default.
_DDL = (
    ("epistemic_type", "TEXT NOT NULL DEFAULT 'observed'"),
    ("works_when", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ("avoid_in", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ("confidence", "DOUBLE PRECISION"),
    ("evidence_run_ids", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ("evaluation_ids", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
)


def upgrade() -> None:
    # `ADD COLUMN IF NOT EXISTS`, spelled as raw SQL like migration 025, not
    # `op.add_column`: the chain is re-applied over already-migrated schemas
    # (stamp-back + re-upgrade is a live repair path, and the Canvas store
    # conformance suite drives it), where a bare ADD COLUMN dies on
    # DuplicateColumn even though the schema it would build is the schema that
    # already exists — #1194's 045 broke CI's coverage (PostgreSQL) leg exactly
    # this way. Each defaulted column stays NOT NULL; its server_default
    # backfills existing rows. `confidence` is the one nullable column: NULL is
    # the modeled "never measured" state, and promotion treats it as a blocker.
    for name, ddl in _DDL:
        op.execute(f"ALTER TABLE learnings ADD COLUMN IF NOT EXISTS {name} {ddl}")
    # Promotion now asks "which rows may promote" across applicability and
    # confidence; this index serves the candidate scan the same way
    # idx_learnings_scope serves the scope-filtered reads.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_learnings_promotion_candidates "
        "ON learnings (org_id, status, hit_count)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_learnings_promotion_candidates")
    for name, _ddl in reversed(_DDL):
        op.execute(f"ALTER TABLE learnings DROP COLUMN IF EXISTS {name}")
