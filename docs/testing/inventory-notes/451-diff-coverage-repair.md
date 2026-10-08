---
inventory-delta:
  packages/maistro-rsi/tests: +7
  packages/maistro-evolve/tests: +3
---

# 451 repair round — diff-coverage floor on the #304 gate-evidence surface

The merge-queue quality gate failed on Pillar 1 (per-file diff coverage,
90% lines / 80% branch arcs over the lines this branch changed): ten changed
lines in the #304 truthfulness surface had no coverage in the suite CI
actually measures them with.

## Why the gap existed

CI measures each package's sources under that package's own suite
(`quality.yml` `coverage-unit` producers). The uncovered behavior was
exercised *cross-package* — `maistro-rsi` tests drive
`maistro_evolve.scorecard` — but cross-package execution is not measured by
the evolve producer, and the rsi-side legs of `_run_lint_tool` were stubbed
at the function boundary in every existing test, so their internal
failure legs never ran.

## What moved

`packages/maistro-evolve/tests/test_scorecard.py` (+3): explicit
`resolved_state()` precedence, the four-way `explain()` mark rendering
(`[PASS]` / `[FAIL]` / `[NOT RUN (blocking)]` / `[UNAVAILABLE]`), and
not_run-vetoes vs unavailable-does-not.

`packages/maistro-rsi/tests/test_gate_evidence.py` (+6): the three genuine
non-execution legs of `_run_lint_tool` (unimportable module → `missing`,
wedged past `_LINT_TIMEOUT` → `timeout`, unspawnable binary → `error`, each
via a real subprocess), `_tool_version` of an absent dist → None,
`_candidate_sha` for a real worktree / unspawnable cwd / non-worktree, and
the bandit unreadable-output FAILED leg with its provenance.

One of the +7 is the salvage commit at head `b0846d09d` (driver-committed):
`test_non_boolean_gate_verdict_fails_closed`, pinning `_project_gates` in
`harvest.py` — only a genuine JSON boolean projects as a recorded verdict;
anything else fails closed to FAILED instead of scoring as passed via
Python truthiness (`bool("false")` is `True`).

No tests were moved, renamed, or removed.
