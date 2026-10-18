---
inventory-delta:
  packages/maistro-design/tests: +19
---
# Cross-artifact consistency evaluation (#779)

Adds `packages/maistro-design/tests/test_consistency.py`: 19 tests for the new
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
  clean-project pass case;
- repair-round additions: sibling contradictions probe each side an artifact
  actually carries; shared origin requires an *affirmative* decision mention
  (a prohibitive mention is local, not shared); and a snapshot whose
  `project_id` mismatches the Run's canonical project is rejected rather than
  misfiled under the wrong project's provenance.

## Repair-round record (exact-debt-ledger)

- The 14 identities the new modules add to the vulture scan (12 result-contract
  Pydantic fields, the Pydantic-invoked `ClaimRule._require_evidence_backing`
  validator, and the `@register_node`-registered `ConsistencyEvalNode`) are
  annotated at their declaration/decorator lines with inline vulture markers
  (`noqa: V102/V105/V107`, codes registered in ruff `external`) instead of
  being banked as ledger debt — `quality/vulture-baseline.json` is unchanged
  and stays exact (1402 reviewed identities → 1402 findings, no deltas).
- One genuinely dead local (`covered`, a write-only list in the factual-claims
  check) was removed while refactoring `_check_factual_claims` below the
  C901 complexity ceiling (per-claim judgment extracted into
  `_judge_allowed_claim`/`_impact_of_pattern`; messages byte-identical).
- `maistro_design.consistency` is reachable from a production entry point:
  `POST /v1/design/projects/{id}/consistency` (`routes.design`, a
  hive-conductor dynamic root) is the Design Studio's synchronous inspection
  surface over the same pure evaluator the `design.consistency_eval` node
  runs, so the module needed no reachability-baseline entry (the earlier
  repair-round baseline entry is removed again — it could never carry the
  prior landed `reachability` authorization the two-merge rule requires).
  Route tests: `docs/testing/inventory-notes/779-design-consistency-route.md`.

Browser E2E (Design Studio UI) is out of scope for this slice: the evaluator
and node land in `maistro-design` with deterministic, relationship-driven
routing; the acceptance E2E needs the workspace UI harness and is tracked
separately.
