---
inventory-delta:
  tests/: +1
---

# PR #2263 absorbs develop's under-recorded root-suite drift

develop commit `1ddfea4f` ("Complete branch-independence migration:
machine-derived baselines as branch-independent evidence", #2334) migrated
`docs/testing/inventory/baseline.json` and the per-change delta ledger, and the
landed root-suite count is one node ID low: develop's own `test` job at that
commit failed the same step —
`DRIFT tests/: expected 5888, collected 5889` (run 40178753871, job
121125061243) — and this branch, whose merge base is that commit, collects the
identical 5889 root-suite node IDs (first-hand `pytest tests/ --collect-only -q`
at both `1ddfea4f` and this head: 5889 each, node-ID sets byte-identical).

This branch adds no test under `tests/` — `git diff 1ddfea4f..HEAD -- tests/`
is empty — so the +1 is not this change's movement. It is recorded here, at the
branch that measured it, per ADR-082526-547c ("the sum absorbs whatever else
merged") and the same remedy `k770-develop-root-suite-drift.md` applied when a
prior develop migration under-recorded the root suite. **No test was added or
removed by this note.** The follow-up note `ops-folded-notes-evidence-2336.md`
(#2336) is correct and untouched; its `tests/: +3` is independent of this +1.
