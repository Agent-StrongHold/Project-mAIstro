# Repair notes — issue #46 round @ 4b600c9788 (schedule-fire -> Conductor real scenario)

## What this round addressed

The prior round's NEEDS-REPAIR verdict (job 31e7b5ad..., head da3fd886ba) left
exactly one locally-actionable finding: **AC6** — the strict-#459 scenario
token `REAL_SCENARIO_EVIDENCE: schedule-conductor` was produced nowhere, so
`REAL_SCHEDULE_CONDUCTOR_SCENARIO` stayed a permanently-evidenced blocker and
the schedule-fire -> Conductor parity scenario (scenario 2) had no real
execution evidence. AC7 (#1199/#2467 exact-head closure evidence on GitHub)
and the GH006 merge-queue enqueue are GitHub-side and prohibited to this lane;
CI gates were already green.

## Change

Scenario 2 is now the production boundary end to end
(`tests/cross_product_parity/test_cross_product_parity.py`):

- Producer: `_ScheduleRunner._tick` — the shipped Hive scheduler tick resolved
  through the same engine seam production reads
  (`get_engine()._agent_port.container`) — against the supported durable
  SQLite spine (`open_durable_profile`). Real durable `ScheduleStore` row;
  selection via `ScheduleStore.due()`; admission through the Container-owned
  `ScheduleRunAdmitter`; consumption through the Container's own
  `execute_admitted_runs_accounting` borrowed unbound onto
  `_ParityScheduleContainer` (which carries only real spine stores plus
  `canonical_store_for_tests()` — no second consumer or admitter
  implementation exists anywhere in the scenario).
- Observer: Conductor's #1036 inspection seam (`visible_run_detail`,
  `list_visible_runs`, `can_inspect_run`, `visible_run_ids`) over the same
  canonical stores, wired exactly as scenario 1 wires it.
- Pinned invariants: exactly one canonical Run per firing; provenance on the
  Run (`admission_source=schedule`, `schedule_id`, `scheduled_for`,
  `schedule_trigger=recurring`, `catchup` bool); durable cursor advancement
  (`runs_so_far=1`, `last_run_id`, `next_due_at > now`, still enabled);
  projection store has no row for the Run; physical NodeRun/Attempt evidence
  through the scoped seam; foreign-Workspace refusal indistinguishable from a
  missing id; a second production tick admits nothing new.

Determinism: hourly cron, enumeration cursor 61 minutes back, catchup window
7200s. An open 61-minute window always contains exactly one hour mark (period
60) and the horizon always contains it — the first draft (30-minute cursor,
default 1h horizon) had a ~50% zero-occurrence window and was caught by the
test itself failing before commit.

Guard/test updates: `REAL_SCHEDULE_CONDUCTOR_SCENARIO` moved from the
scaffold-guard's must-stay-blocked list to must-be-available;
`test_schedule_fire_has_canonical_admission_and_shared_inspection_seams` is
unconditional; `test_schedule_required_scenario_emits_strict_closeout_evidence`
requires `PASSED` + `executed is True`. Scenarios 3 (Evolve) and 6 (golden)
remain deliberate strict-mode blockers owned by #51/#1064-66 and #463.

## Validation evidence (all run locally at 4b600c9788)

- `uv run pytest tests/cross_product_parity/ -q` — **26 passed** (26 before:
  node counts unchanged, bodies replaced in place).
- `uv run python scripts/run-m1-closeout.py` — strict fail-closed closeout:
  `scheduler-occurrence-to-conductor {"executed": true, "status": "PASSED"}`;
  only evolve/golden scaffold scenarios fail (by design, other issues' work).
- Negative control: the closeout test failed for real during development when
  admission produced 0 Runs (the wall-clock window bug above) — it fails
  against the regression it names.
- `uv run ruff check .` / `uv run ruff format --check .` — clean (3628 files).
- `uv run python scripts/check-suite-inventory.py` — ok, 21 suites match;
  duplicates 0. `check-test-duplicates.py` ok; `check-doc-links.py` ok;
  `check-backlog-consistency.py` OK.
- Adjacent suites (the surfaces the scenario leans on):
  `packages/hive-conductor/backend/tests/test_scheduler_canonical_admission.py`
  + `packages/maistro-core/tests/runs/test_consumption.py` — 52 passed,
  4 skipped (PostgreSQL legs, no live DB this round).

## Inventory notes

- New: `docs/testing/inventory-notes/issue-46-schedule-conductor-scenario.md`
  (`inventory-delta: tests/: +0`).
- Addendum on `issue-1199-canonical-scheduler.md` superseding its head-scoped
  "token produced nowhere" statements.

## Residual (outside this lane)

- AC7: #1199/#2467 exact-head closure evidence and issue closes are GitHub
  mutations — prohibited here.
- GH006 merge-queue enqueue is GitHub-side.
- Strict-#459 scenarios 3/6 remain red until Evolve (#51/#1064-66) and the
  golden real-observation (#463) scenarios are executed for real.
