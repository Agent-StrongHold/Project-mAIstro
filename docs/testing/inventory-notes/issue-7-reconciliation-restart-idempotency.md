---
inventory-delta:
  packages/maistro-core/tests: +2
---

Adds two regressions to the Goal reconciliation production suite: `test_replayed_physical_admission_returns_the_existing_run` asserts repeated fulfilment returns one Run id and leaves one canonical Run; `test_crash_after_run_insert_replays_one_canonical_run` crashes after physical admission but before control-plane completion, then verifies reconciliation repair retains exactly one canonical Run and completes the admission.
