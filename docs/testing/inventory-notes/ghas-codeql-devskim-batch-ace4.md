---
inventory-delta:
  tests/: +4
  packages/hive-conductor/backend/tests: +1
---
# GHAS CodeQL + DevSkim backlog batch (ace4)

- Two new parametrized cases in `tests/test_devskim_scan_scope.py`
  (`test_the_noisy_trees_are_still_excluded`) pin the added ignore-globs
  (`packages/hive-conductor/eval/**`, `quality/**`).
- `tests/test_mutation_baseline.py`: scheduler-write failure scrubbed via
  `_ci_error_annotation` (+1).
- `tests/test_vendor_bfcl_pins.py`: import coverage for `WHEEL_SHA256` (+1).
- `packages/hive-conductor/backend/tests/test_ui_auto_climb_defaults.py`:
  dunder-main delegates to `main()` (+1).
