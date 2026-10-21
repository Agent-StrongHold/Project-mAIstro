---
inventory-delta:
  packages/maistro-core/tests: +16
  packages/maistro-design/tests: +46
---
<!-- Measured by scripts/check-suite-inventory.py --update; see README.md. -->
# 795-design-loop-proof

Issue #795 (M7-A6): one public proof Run with an inspectable
Goal→Rubric→Explore→Execute→Evaluate→Refine lineage, plus the lineage read
model the proof (and later the Design Studio inspector) answers from.

## This change's own delta

`packages/maistro-core/tests` **+16**:

- `runs/test_run_lineage.py` **+15** — `maistro.runs.lineage`
  (`run_lineage`/`artifact_lineage`) as a read model over the shared
  three-backend `spine` fixture: the projection carries Graph snapshot identity
  (graph_id, content hash, definition), every NodeRun with its semantic
  `node_name` from the Graph definition, every Attempt in ordinal order, and
  every `RunEvalScore` grouped onto the Attempt that earned it; an artifact
  resolves to its producing Attempt (including nested inside an Attempt
  result), an artifact the Run never made raises `ArtifactNotInRunLineage`
  instead of a guessed answer, Rubric/Goal bindings derive from persisted eval
  records only, and an unknown Run raises `RunNotFound`. Five tests × three
  backends; the Postgres leg skips without `MAISTRO_TEST_PG_DSN` exactly like
  every other conformance suite.
- `projects/test_rubric_store.py` **+1** — a retried `RubricStore.create()` of
  identical content is idempotent and preserves the stored revision's
  `created_at` instead of minting a fresh timestamp behind the caller (the
  proof's redirect step re-walks creation paths, so retries are real there).

`packages/maistro-design/tests` **+20** — `test_design_loop_proof.py`: the
M7-A6 scenario executed end to end through canonical APIs only, on both the
in-memory and SQLite `RunStore` backends (10 tests × 2 backends): the planted
`claim_evidence` failure is durable on the Run before refine and the scorer is
real (fails unevidenced claims, passes evidenced ones); park → redirect-Rubric
(same Goal revision, v1 immutable) → accept are canonical human pauses; a
mid-loop refresh re-reads Goal, Rubric revisions, Run, and all six eval records
from the stores; both refine-side Attempts are visible, the failed record
survives, and the accepted artifact names the winning re-evaluation Attempt;
the Canvas-unavailable branch records exactly that with no artifact while the
loop completes on the non-Canvas branch, and the Canvas-available branch
produces on the same Run id; the full lineage chain from the accepted artifact
to both Rubric revisions and the Goal revision is queryable, with the pack
identity proven by the snapshot's `source_template` provenance; and the proof
advances only on decisions (no timers).

## Residual delta recorded here on purpose

`packages/maistro-design/tests` also drifted **+26** before this change:
`test_packs.py` grew across #793 (M7-A4 domain packs) and #794 (M7-A5 HITL
fence on waiting NodeRuns), both of which landed without an inventory note on
this branch's history. The gate is per-tree, not per-author, so this note
records the whole drift — +46 = 20 (this issue) + 26 (attributed above) — to
bring `expected = baseline + Σ deltas` back to the collected count. The
attribution lives in this prose, not in a second note, so the ledger keeps one
delta per suite per change and nothing shares a mutable line.
