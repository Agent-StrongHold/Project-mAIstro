# verify-92-durable-schedules-fa3391e5

> This note carries **no `inventory-delta:` block**: it adds and removes no
> tests, and the gate (ADR-082526-547c) reads an absent key as zero movement.
> It follows the verification-record precedent of
> `verify-epic20-m3b-disposition-c5e070d9.md`.

First-party verification record for lane L92 (issue #92 — M3-B2, make
recurring schedules survive restart) at head
`fa3391e5e925e342d6b2a244f29abe058b1b0c13` (branch `auto-92`, develop base
identical, tree clean). The job's driver produced **no** `check-*.log` files
(`manifest.checks` empty); every claim below was executed first-party at the
exact head. This note moves no test counts.

## Executed evidence

- `uv run pytest packages/maistro-core/tests/scheduling -q` — **272 passed,
  36 skipped** (PostgreSQL cases skip without `MAISTRO_TEST_PG_DSN`).
- Dedicated pgvector/pgvector:pg18 container, migrated with
  `DATABASE_URL=... uv run alembic upgrade head` (043→047 applied), then the
  same suite with `MAISTRO_TEST_PG_DSN` set: **308 passed, 0 skipped,
  0 failed**. This is the #850 multi-replica evidence run for real:
  `test_pg_admission.py` (two ticker replicas share occurrence identity
  across a timezone edit), `test_admission_backend_parity.py`,
  `test_store.py[postgres]` (second store handle sees the row),
  `test_schedule_winner_crash.py` (winner-crash persistence, together with
  `packages/maistro-core/tests/persistence` — 23 passed).
- Hive scheduler surface:
  `uv run pytest packages/hive-conductor/backend/tests/test_scheduler.py
  test_scheduler_bounded_tick.py test_schedule_frequency_floor.py
  test_schedule_canonical_definitions.py test_scheduler_canonical_admission.py
  test_manual_fire_canonical.py -q` — **138 passed**.
- `uv run ruff check` + `uv run ruff format --check` on
  `packages/maistro-core/src/maistro/scheduling`,
  `services/scheduler.py`, `routes/schedules.py` — clean.

## Acceptance disposition at this head

Met, with code-level evidence:

1. **Durability chain is real.** `/v1/schedules` writes the canonical
   `ScheduleStore` first (`put_canonical_definition`,
   services/scheduler.py:245) and the Hive row second; both are
   write-through to SQLite in a configured deployment
   (`services/foundation.py:118` calls `stores.configure_persistence`
   unconditionally; `ModelStore.__setitem__` persists before the memory
   mutation). The Container wires `SqliteScheduleStore`/`PgScheduleStore`
   (`runs/wiring.py:248,265-275`) — never the in-memory fallback — when a
   DB is configured. Boot reloads Hive rows (`initialize_stores`) and the
   runner backfills canonical definitions before its first tick.
2. **Resume without duplicate/missed firing.** The cursor lives in the
   canonical store, not the Hive row (`test_scheduler.py:743`, "A restart
   loses the row's `last_run`; the store's is what counts"), and catch-up
   honors the per-schedule window with truthful truncation.
3. **Multi-replica occurrence identity (#850).** Claims are UTC instants
   (`canonical_occurrence_instant`), probed against the Run store so one due
   occurrence admits one Run; proven against real PostgreSQL above.
4. **Startup reconciliation idempotent.**
   `test_backfill_puts_a_missing_row_once_and_never_rewinds_its_cursor` and
   the drifted-row test prove re-running backfill neither rewinds cursors
   nor resurrects disabled rows.
5. **Schedule state vs Run state separate.** `schedules` table holds
   definitions+cursor; occurrence claims are Run-store rows; the admitter is
   the only bridge.
6. **Bounded catch-up (#1200).** `EnumerationLimits` bounds window/steps/
   wall-time with reported incompleteness; cron parsing is memoized;
   `test_a_stale_backlog_tick_stays_within_bounded_wall_time` runs a
   seven-day per-minute backlog (~10k occurrences) through the full tick in
   < 2 s.
7. **Frequency floor (#1200).** `routes/schedules.py` 422s create/update
   below `schedule_min_frequency_gap_s` (measured via `minimum_gap`, so
   list/step forms are honored); the setting and the window cap are
   validated at startup and out-of-range config fails loudly
   (`test_floor_and_cap_settings_outside_the_safe_bounds_fail_at_startup`).
8. **Policy documented.** ADR-082126-f69c §5/§7 and the `config.py`
   settings comments state the catch-up and floor policy;
   `docs/testing/inventory-notes/1200-bounded-schedule-catchup.md` records
   the +35 tests.

## Unmet acceptance criterion (blocks MERGE-READY)

- **Restart E2E on the canonical #1199 tick path does not exist.**
  SPEC-080126-3a7c's Testing section requires "create → restart the app →
  confirm re-registration and next fire … it has to survive a real process
  boundary", and its first acceptance checkbox is unchecked. No test in the
  tree drives `POST /v1/schedules` against a real `maistro.state.State`
  SQLite file, reopens the app over the same file, and fires on the
  canonical tick path (the nearest tests are store-level:
  `test_sqlite_schedules_survive_a_reconnect`; unit-level:
  `test_scheduler.py:743` with a fake store; the durability-pattern
  template exists in `test_settings_durability.py:316`). Per issue #92's
  own last criterion, the KNOWN-GAPS entry ("Recurring schedules created
  through the API do not survive a restart", KNOWN-GAPS.md:106) may close
  **only after** that E2E exists and passes. The entry is still open —
  consistent, and its in-memory wording predates the durability wiring, but
  closing it now would be unevidenced.

## Residual observations (non-blocking)

- The runner's backfill runs inside the async runner loop, so the app may
  accept traffic seconds before the first-tick backfill completes;
  SPEC-080126-3a7c words the ideal as "re-register before the app accepts
  traffic". Ticks are minute-grained, so exposure is negligible, but the
  E2E/repair may note it.
- `ScheduleRunner.run()` swallows `scheduler_start_failed` as a warning
  (main.py:211) — a scheduler that failed to start is logged, not fatal;
  worth an operator-visibility check in the E2E round.
