---
inventory-delta:
  tests/: +2
---
# GHAS CodeQL + DevSkim backlog batch (ace4)

Two new parametrized cases in `tests/test_devskim_scan_scope.py`
(`test_the_noisy_trees_are_still_excluded`) pin the added ignore-globs:

- `packages/hive-conductor/eval/departments/engineering.py`
- `quality/vulture-baseline.json`

No other suite deltas: mutation-baseline and ui_auto_climb changes reuse
existing coverage (`_ci_error_annotation`, `DEFAULT_CLIMB_URL` defaults).
