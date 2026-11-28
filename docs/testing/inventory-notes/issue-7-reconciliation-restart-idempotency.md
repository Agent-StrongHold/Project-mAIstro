---
inventory-delta:
  packages/maistro-core/tests: +3
---

Adds three regressions to the Goal reconciliation production suite: `test_replayed_physical_admission_returns_the_existing_run` asserts repeated fulfilment returns one Run id and leaves one canonical Run; `test_crash_after_run_insert_replays_one_canonical_run` crashes after physical admission but before control-plane completion, then verifies reconciliation repair retains exactly one canonical Run and completes the admission. `test_reopened_container_sweep_repairs_the_lapsed_physical_admission` leaves a real claim and admission open on disk, closes the SQLite container, and drives the replacement through the normal bounded sweep. It checks that the live lease prevents early takeover and that expiry repairs the original queued Run without knowing its Goal id at tick time. With the pre-fix `GoalRunAdmitter.admit` from `8be9d42d96`, the reopened-container assertion fails on two distinct queued Run ids.

Scope: this covers a Goal already registered with reconciliation. In a separate file-backed SQLite probe, `container.goal_store.create_goal(...)` alone followed by `container.reconcile_goals()` returned zero decisions; the reconciliation store returned no control row and the Run list was empty. The bounded sweep is not by itself a discovery bridge from a canonical commit. PostgreSQL failover is also not covered: `wire_goal_reconciliation` selects a process-local store for that backend.
