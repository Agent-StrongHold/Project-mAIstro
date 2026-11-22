---
inventory-delta:
  tests/: +0
---
# Issue #46 — schedule-fire -> Conductor parity scenario becomes a real execution

Scenario 2 of the #459 cross-product parity suite
(`tests/cross_product_parity/test_cross_product_parity.py`) stopped being a
scaffold. `_schedule_conductor_scenario` now executes the production boundary
end to end and the closeout machinery records it as executed evidence:

- producer: `_ScheduleRunner._tick` — the shipped Hive scheduler tick, resolved
  through the same engine seam production reads — against the supported durable
  SQLite spine (`open_durable_profile`). The schedule is a real durable
  `ScheduleStore` row; the tick selects it via `ScheduleStore.due()`, admits the
  one due occurrence through the Container-owned `ScheduleRunAdmitter`, and
  consumes the admitted Run through the Container's own borrowed
  `execute_admitted_runs_accounting` method (no second consumer implementation).
- observer: Conductor's #1036 inspection seam (`visible_run_detail`,
  `list_visible_runs`, `can_inspect_run`, `visible_run_ids`) over the same
  canonical stores, plus the projection-store absence check.
- pinned invariants: exactly one canonical Run per firing; schedule provenance
  on the Run (`admission_source=schedule`, `schedule_id`, `scheduled_for`,
  `schedule_trigger=recurring`); durable cursor advancement
  (`runs_so_far`, `last_run_id`, `next_due_at`); physical NodeRun/Attempt
  evidence; foreign-Workspace refusal; a second production tick creates no
  second Run (occurrence claim + persisted due cursor, not a disable).

The occurrence is deterministic by construction: hourly cron with the
enumeration cursor 61 minutes back and a two-hour catchup horizon — an open
61-minute window always contains exactly one hour mark, so the scenario has no
zero-or-one flake window against the wall clock.

The marker `REAL_SCENARIO_EVIDENCE: schedule-conductor` therefore reads as
available, and `REAL_SCHEDULE_CONDUCTOR_SCENARIO` moved from the
"must stay blocked" list to the "must be available" list in
`test_scaffold_only_scenarios_stay_blocked_until_real_execution_lands`.
Scenarios 3 (Evolve) and 6 (golden observation) remain scaffold blockers owned
by #51/#1064-66 and #463; strict mode stays red on them by design.

Node-ID counts are unchanged (bodies replaced in place; no test added or
removed: 26 before, 26 after). Strict-closeout development diagnostics:
`scripts/run-m1-closeout.py` now shows `scheduler-occurrence-to-conductor`
`executed=true, PASSED`; the only remaining failures there are the two
scaffold scenarios above.
