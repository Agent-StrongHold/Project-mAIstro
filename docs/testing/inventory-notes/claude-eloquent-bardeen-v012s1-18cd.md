---
inventory-delta:
  packages/maistro-canvas/tests: +1
---
# Canvas pre-stage worker-loss regression (#1550)

The retry-ceiling guard and two exhausted-receipt unit regressions from the
original PR are already on develop through #1560. This refresh adds only
`test_canonical_executor_integration.py::test_simulated_pre_stage_worker_losses_respect_the_retry_budget`.

The real production composition runs repeated simulated pre-stage claim losses,
then recovery, claim refusal and canonical reaper terminalization against the
shared detached/CAS job-store fake. A fresh-job positive control proves the
provider remains connected. This is hermetic coroutine/lease-expiry simulation,
not an OS process-kill or PostgreSQL durability test. No tests are removed.
