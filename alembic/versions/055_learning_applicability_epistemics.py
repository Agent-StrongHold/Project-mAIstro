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
  for metrics: absent is not zero). `054_learning_lifecycle_columns` landed
  this column first with `NOT NULL DEFAULT 0.5` — the develop-side WIP
  reading — so this migration drops the NOT NULL constraint to restore the
  modeled "never measured" state (rows written before the drop read back as
  0.5 through the decode default, and promotion still blocks them at the
  floor; the honest NULL returns on the next unmeasured write).
- The JSONB applicability/evidence columns default to `'[]'` and
  `epistemic_type` to `'empirical'` — the honest reading of every pre-M4-B row
  under the reconciled pipeline epistemics (ADR-100126-8c2d): a captured tool
  correction is empirical-by-construction and had no applicability recorded.
  `054` already created `epistemic_type` with exactly that default, so the
  `IF NOT EXISTS` guard makes this migration's own declaration a no-op twin
  of it.
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

Revision ID: 055
Revises: 054
Create Date: 2026-10-01
"""

from __future__ import annotations

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None

# Renumbered five times per the chain's standing collision convention (see
# 046's docstring): first from "048" on parent "047" when develop claimed that
# id for `048_canvas_job_retry_backoff` on the same parent, then from "051" on
# parent "050" when the auto-780 develop sync brought
# `051_canonical_run_eval_scores` (#792) onto that same parent, then from
# "052" on parent "051" when a develop sync brought
# `052_learning_stage_ladder` (M4-B1, ADR-103) onto that same parent, then
# from "053" on parent "052" when the M4-B5 develop sync (#1753) brought
# `053_learning_lifecycle_columns` onto that same parent, and finally from
# "054" on parent "053" when the auto-82 sync (issue #82, PR #1702) landed:
# this branch's backlog work source (#82) had taken `053` on the `052` parent
# first, so the learning-lifecycle columns re-parented onto that backlog tip
# as `054_learning_lifecycle_columns` and this migration — landing second
# once more — re-parents onto that tip as `055`. Each collision leaves two
# revisions sharing one id and two heads — `alembic history` fails outright
# on that shape. This migration now attaches after
# `054_learning_lifecycle_columns`, keeping exactly one head.

# Column DDL, in declaration order. The defaults are expression text (the cast
# `'[]'::jsonb` is SQL, not a JSON value), matching what the SQLite twin's
# in-place upgrade writes. `epistemic_type` and `confidence` are already on
# the table (054 created them), so their IF NOT EXISTS adds no-op; the DROP
# NOT NULL below is this migration's real word on `confidence`.
_DDL = (
    ("epistemic_type", "TEXT NOT NULL DEFAULT 'empirical'"),
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
    # 054 created `confidence` as NOT NULL DEFAULT 0.5; the record's own
    # semantics need NULL = "never measured" (a promotion blocker), so the
    # constraint goes. Existing rows keep the 0.5 they were backfilled with —
    # the decode default reads them the same way — and the next unmeasured
    # write stores an honest NULL.
    op.execute("ALTER TABLE learnings ALTER COLUMN confidence DROP NOT NULL")
    # 054 also left DEFAULT 0.5 on the column; an INSERT that omits confidence
    # must store the honest NULL (never measured), not fabricate a measurement.
    # Rows 054 backfilled keep their 0.5; only future omissions write NULL.
    op.execute("ALTER TABLE learnings ALTER COLUMN confidence DROP DEFAULT")
    # Promotion now asks "which rows may promote" across applicability and
    # confidence; this index serves the candidate scan the same way
    # idx_learnings_scope serves the scope-filtered reads.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_learnings_promotion_candidates "
        "ON learnings (org_id, status, hit_count)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_learnings_promotion_candidates")
    # Restore 054's shape before dropping this migration's own columns: the
    # NOT NULL it declared needs the modeled-NULL rows backfilled to the same
    # default 054 backfilled with. 054 owns `epistemic_type` and `confidence`,
    # so they are not dropped here.
    op.execute("UPDATE learnings SET confidence = 0.5 WHERE confidence IS NULL")
    op.execute("ALTER TABLE learnings ALTER COLUMN confidence SET NOT NULL")
    for name, _ddl in reversed(_DDL):
        if name in ("epistemic_type", "confidence"):
            continue
        op.execute(f"ALTER TABLE learnings DROP COLUMN IF EXISTS {name}")
