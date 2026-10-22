---
inventory-delta:
  packages/maistro-core/tests: +8
---

# auto-106-review-findings

Closes the remaining review findings on the M4-I verification slice; every
test below fails against the behavior it names.

- `test_verification_supervision.py` (+6): escalation now runs before the
  post-state check, so a withheld cheap visit is not judged as the final
  world (and the accepted escalated visit still is); a malformed (`NaN`)
  quality report is a finite shortfall instead of an unserializable
  escalation; a human pause is supervised on its result-state claim where it
  happens; and plan consumption is seeded from durable completed NodeRuns so
  a later mismatch does not report an earlier step as still awaited.
- `test_llm_summarize_verification.py` (+1): text-only observations route to
  the configured `text_model`, rather than silently clinging to `model`.
- `test_routing.py` (+1): an image carried inside a nested content-part list
  encodes with that part's URL instead of an empty reference.

Touched test files only; no suite added or removed.

## Validation (local, worktree `/home/dev/Git/wt/auto-106`)

- `origin/develop` (`485392ecd`) merged in before the repair; no conflicts.
- Focused suites: 93 passed (`test_verification_supervision.py`,
  `tests/graph/verification/`, `test_llm_summarize_verification.py`); full
  `packages/maistro-core/tests/graph` 2150 passed / 136 skipped / 4 xfailed.
- Full core suite under coverage: 15960 passed / 1153 skipped / 7 xfailed.
- Root suite (CI's coverage producer argv): 5522 passed / 139 skipped.
- `scripts/check-diff-coverage.py` against `origin/develop`: every measured
  file at or above 90% lines / 80% branch arcs.
- `tests/test_complexity_gate_scope.py`, `tests/test_ci_quality_split.py`,
  `tests/test_bench_m4i_adaptive_vs_fixed.py`: 109 passed.
- `check-radon-baseline.py`, vulture (CI argv), suite inventory (21 suites,
  32839 node IDs), workflow inventory/write-safety, backlog, reachability,
  duplicate-test gate: clean. `mypy packages/maistro-core/src`: clean.
