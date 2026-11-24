---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# 1064-restore-fail-closed-latch

One node ID added to `packages/hive-conductor/backend/tests` (in
`test_evolution_startup_wiring.py`); no test removed or renamed.

- `test_broken_restore_fails_closed_against_admission_and_cadence` — closes
  the review gap the #1064 fail-closed latch addresses: when the durable
  domain restore fails and the service falls back to the honest fresh init,
  that inspectable-but-fabricated population must not be captured as the
  newest admission snapshot. The leg asserts the latch keeps `/status`
  unavailable with a restore-named reason even with a healthy canonical
  engine, that the manual admission boundary (`_run_one_cycle_locked`, the
  `/cycle` route's 503 path) raises `EvolutionUnavailableError`, and that the
  failure is observable in the `/status` payload (`restore_failed`). The two
  neighbouring restore legs now also pin that a healthy fallback (missing
  workspace key, empty-but-healthy store) leaves the latch unset, so only a
  real restore failure blocks execution.
