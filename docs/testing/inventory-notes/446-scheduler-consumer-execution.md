---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# Scheduler consumer execution is strict-closeout evidence (#446 repair)

The 2026-09 verifier pass on the #446 strict closeout found that the parity
scheduler scenario asserted a QUEUED Run only: its hand-built container had no
`execute_admitted_runs`, and `ScheduleRunner.run_once` swallowed the resulting
missing-method `AttributeError` behind the same `except Exception` that
contains a failing consumer tick. Strict closeout therefore proved schedule
*admission* but not scheduler NodeRun/Attempt *execution* — the
persisted-but-unreachable shape the M1 evidence rule rejects.

## Changes

- `services/scheduler.py` — `run_once` validates that a configured Container
  has a callable canonical consumer **before** it evaluates/admit any schedule;
  `fire_now` applies the same preflight before manual admission. Missing wiring
  raises `ScheduleAdmissionUnavailable` while a consumer that raises remains
  contained and logged (per `test_scheduler_tick_logs_consumer_failure`).
  Thus neither producer can persist a Run or move a schedule cursor when its
  configured process has no execution owner.
- `tests/cross_product_parity/test_cross_product_parity.py` — Scenario 2
  (`test_schedule_fire_admits_and_executes_a_canonical_run_from_the_live_runner`)
  now starts the shipped engine composition (bridge-built Container over a
  durable SQLite spine), seeds a schedule whose template names the registered
  shipped node kind `transform.alias_keys`, and requires the live
  `ScheduleRunner().run_once` cadence to produce a **completed** canonical Run
  -> NodeRun -> Attempt chain: one completed NodeRun, one completed Attempt
  with `executor_id == schedule-consumer`, schedule provenance correlation
  (`admission_source`/`schedule_id`/`scheduled_for`), observed through an
  independent connection and the Conductor `visible_run_detail` observer with
  identity projection. No node-count change: the scenario replaces the
  queued-only assertion in place (rename included).
- Hive regression
  `test_scheduler_refuses_admission_when_container_lacks_consumer_seam`
  (the existing +1 node): a due recurring row and a manual fire against a
  real admission-wired fixture without `execute_admitted_runs` both raise
  `ScheduleAdmissionUnavailable` **before** a Run, canonical schedule row, or
  product cursor is written.

Also corrected `docs/architecture/CONVERGENCE-MATRIX.md`'s Builders evidence
cell, which claimed `builders.graph_executor` was deleted while the module
ships the canonical adapter (`CanonicalGraphPipelineExecutor`); the cell now
states the true retirement (the pre-convergence in-process executor is gone,
the canonical adapter remains), matching the disposition cell and row 59.
