# #1199 round: strict #459 schedule→Conductor closeout scenario executed for real

Scope snapshot: issue #1199 only, branch `auto-1199`, starting head
`fef3e272f317a440b1e5417a03cbc0dbe2e2567b`, develop base
`204f2924887c9b282cf4e372569cee1577dd9a0f`. The prior round's only recorded
block was the driver's `pytest packages/maistro-core/tests/conftest.py`
(exit 5 — no tests collected, a file with no test functions), not scheduler
behavior; this round addresses the one acceptance criterion the previous
round explicitly recorded as UNVERIFIED.

## What this round changed

Criterion 6 of the current reactivation — "Strict #459 tests actual
configured scheduler lifespan, due tick → canonical Run/Attempt → Conductor,
DB reopen and no stale projection restore" — was still served by an
abstaining scaffold: `_scheduler_scenario()` raised `ScenarioAbstained`, so
`test_schedule_required_scenario_emits_strict_closeout_evidence` recorded
`executed=false` and strict mode stayed red for scenario 2. The scaffold is
replaced by a real execution (`tests/cross_product_parity/
test_cross_product_parity.py`, `_schedule_conductor_scenario`):

- the producer half starts the shipped scheduler the way the app lifespan
  does (`services.scheduler.start_scheduler`) against a configured core
  `Container` on the durable SQLite spine: the real loop's startup
  `backfill_canonical_definitions()` runs, the due tick admits one claimed
  occurrence through the canonical `ScheduleRunAdmitter`, and the same
  tick's canonical consumer executes it into real NodeRun/Attempt evidence
  while `record_fire` advances the durable cursor
  (`runs_so_far=1`, `last_run_id`, `next_due_at`);
- the observer half is Conductor's landed inspection seam
  (`services.dag_run_inspection`) wired to the same canonical stores: the
  tick recorded no projection row, the Run is discoverable (list), readable,
  and evidence-complete by canonical id for a Workspace member, and a
  foreign caller is refused indistinguishably from a missing id;
- the restart leg closes and reopens the canonical database (real
  `create_container` on the same SQLite file, not a process-local dict),
  reseeds a stale Hive projection row, and starts the lifespan again: the
  durable cursor admits no second occurrence and the stale row is repaired
  from canonical truth — it can neither resurrect the schedule nor override
  the acknowledged definition (#2467);
- the observation carries a strict invariant (`_validate_schedule_observation`)
  so strict closeout PASSED requires the real producer/observer records
  (`cursor_runs_so_far=1`, `restart_new_runs=0`,
  `stale_projection_repaired`).

Supporting edits, deliberately minimal:

- `packages/hive-conductor/backend/services/scheduler.py`: the tick cadence
  literal `asyncio.sleep(30)` becomes the module constant `_TICK_INTERVAL_S
  = 30.0` so a test can drive the real lifespan loop without waiting out the
  production pause. Production behavior is identical (30.0 == 30).
- `SCHEDULER_SCENARIO` now declares `REAL_SCHEDULE_CONDUCTOR_SCENARIO` as a
  dependency and its validator; the scenario's docstring carries the
  `REAL_SCENARIO_EVIDENCE: schedule-conductor` marker, which is exactly what
  clears the dependency's blocker probe.
- `test_scaffold_only_scenarios_stay_blocked_until_real_execution_lands`
  moves the schedule marker into the must-be-available group alongside the
  Builders one (the same replacement the Builders scenario made), keeping
  the evolve/golden scaffolds blocked.
- One closeout-machinery unit reused the removed `_scheduler_scenario`
  callable as a stand-in; it now uses the still-abstaining
  `_evolve_scenario`, preserving that test's semantics.

No test function was added or removed (parity suite: 26 items before and
after), so this note records no `inventory-delta`.

## Negative evidence (the test fails against the regression it names)

With `_project_canonical` temporarily short-circuited to `return 0`
(projection repair disabled), the scenario fails at exactly the stale-
projection assertion — `assert 'stale Hive name' == 'canonical parity
schedule'` — then was reverted and the suite re-passed. The restart/re-fire
assertions are structural (exact `[run_id]` equality after reopen), not
timing-based; all waits poll durable state with explicit timeouts and
failure messages.

## Executed validation (this round, fresh lane-owned pg18 at 127.0.0.1:18999)

New container `auto-1199-r2-pg` from `pgvector/pgvector:pg18`, migrated with
`DATABASE_URL=<dsn> uv run alembic upgrade head` — chain applied through 069
`schedule_deletions` (the #2467 tombstone migration) on a previously empty
database:

- `tests/cross_product_parity/test_cross_product_parity.py -q`: **26 passed**
  (development mode), including the now-real
  `test_schedule_required_scenario_emits_strict_closeout_evidence`;
  `-k "schedule_required or schedule_fire" -s` emits
  `M1_PARITY_EVIDENCE {"executed": true, "status": "PASSED", "scenario":
  "scheduler-occurrence-to-conductor"}`.
- The same tests under `MAISTRO_PARITY_MODE=m1-closeout
  MAISTRO_PARITY_STRICT=1` (`-k "schedule_required or schedule_fire or
  scaffold_only"`): **3 passed** with the same `executed=true, PASSED`
  evidence — the prior round's strict-mode failure for scenario 2 is gone.
  The remaining strict reds are scenarios 3 (Evolve) and 6 (golden
  observation), owned by other issues.
- `MAISTRO_TEST_PG_DSN=<lane pg18> pytest
  packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py
  packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py -q`:
  **65 passed, 0 skipped** on real PostgreSQL — the #2467 regression suite,
  including the retired-policy negative leg and persisted-projection
  restart legs across real close-and-reopen.
- `MAISTRO_TEST_PG_DSN=<lane pg18> pytest packages/maistro-core/tests -k
  schedul -q`: **368 passed** (store conformance, serialized SQLite/PG
  `record_fire`, due-cursor semantics).
- `DATABASE_URL/MAISTRO_TEST_DATABASE_URL/MAISTRO_TEST_PG_DSN=<lane pg18>`
  migration-chain, installed-base Goal-upgrade and capability effect-index
  suites, run sequentially: **28 passed** (apply + reverse, through 069).
- Nine adjacent Hive scheduler suites (scheduler, bounded tick, canonical
  admission/definitions, manual fire, frequency floor, scope, workspace
  scope, timezone health incl. the real `start_scheduler` loop task):
  **176 passed**.
- Gates at this head: `uv run ruff check .` clean; `uv run ruff format
  --check .` (3624 files formatted); canonical mypy over the seven library
  `src` trees (no issues in 959 files); `scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exit 0
  (1221 reviewed identities = 1221 findings — no ledger amendment justified);
  `scripts/check-suite-inventory.py` (21 suites match);
  `scripts/check-durable-table-inventory.py` (125 tables);
  `scripts/check-test-duplicates.py` (0 groups); `scripts/check-doc-links.py`;
  `scripts/check-backlog-consistency.py`; `git diff --check` clean.

## Acceptance accounting (current reactivation criteria)

1. Canonical edit survives restart, stale row repaired: executed on
   memory/SQLite/PostgreSQL (`test_restart_retains_a_canonical_edit_and_repairs_the_stale_row`)
   and now also in the parity scenario (both lifespan legs).
2. Canonical delete cannot resurrect/fire: executed across backends and
   real PG reopen (`test_a_deleted_schedule_is_not_resurrected_and_its_stale_row_is_removed`,
   DELETE-outage regression from the prior round).
3. One-time tombstone-aware legacy migration: executed across backends.
4. Create orphan, repeated/concurrent startup, truthful ack: executed
   (orphan, concurrent-startup, UPDATE/DELETE-outage tests). Independent-
   process import races and combined create-projection/compensation failure
   remain UNVERIFIED, as recorded last round.
5. Cursors, uniqueness, SQLite/PG concurrency: executed (core store suite,
   canonical-due suite, two-runner claim tests) — 368 + 65 items this round.
6. Strict #459 configured lifespan → due tick → canonical Run/Attempt →
   Conductor, DB reopen, no stale restore: **now executed** — the parity
   scenario runs the real `start_scheduler` lifespan, observes through the
   landed inspection seam, reopens the database, and pins projection
   authority; strict mode emits `executed=true, PASSED` for scenario 2.

Original acceptance criteria: canonical-only due tick, projection cannot
force due, no-fire `next_due_at` persistence, SQLite serialized cursor,
occurrence uniqueness, canonical restart — all executed as recorded in the
prior rounds' notes and re-run here (65/368/176 items).

Residual, explicitly not claimed by this round: the issue's "negative-before/
positive-after CI evidence" closure-gate clause requires a CI run on the
integrated branch; this lane cannot push or trigger CI, so that evidence can
only be produced post-integration. Everything else above was executed first-
party in this worktree at the exact candidate head recorded in the commit
that carries this note.
