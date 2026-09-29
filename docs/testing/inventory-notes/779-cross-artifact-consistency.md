---
inventory-delta:
  packages/maistro-design/tests: +15
---
# Cross-artifact consistency evaluation (#779)

Adds `packages/maistro-design/tests/test_consistency.py`: 15 tests for the new
deterministic cross-artifact consistency evaluator
(`maistro_design.consistency`) and its canonical graph node
(`design.consistency_eval`).

Each test maps to an issue acceptance criterion:

- a planted Persona violation proposes only its own branch (local impact
  closure over declared `references` edges, never artifact kinds);
- a planted shared factual contradiction identifies every descendant that
  consumed the bad shared decision, walking `consumes` edges plus transitive
  `references`;
- a locked accepted artifact is reported as conflicting (LOCKED_DECISIONS
  finding, `requires_unlock` target) while the evaluator provably writes
  nothing — the frozen snapshot is asserted byte-identical afterwards;
- provenance cites exact brief version, goal revision, per-decision and
  per-artifact versions, and the evaluation stays interpretable after later
  edits;
- claim rules distinguish provided evidence from model-generated assertions
  (distinct severities, validator-enforced shape, orphan-evidence reporting);
- execution goes through `run_durable_graph`, asserting real
  Run/NodeRun/Attempt provenance for both the failing evaluation and the
  retry after refinement, with the failed evaluation record preserved in the
  store;
- remaining dimensions (terminology, message coverage, channel requirements,
  accessibility, design system) get planted-defect coverage plus a
  clean-project pass case.

Browser E2E (Design Studio UI) is out of scope for this slice: the evaluator
and node land in `maistro-design` with deterministic, relationship-driven
routing; the acceptance E2E needs the workspace UI harness and is tracked
separately.
