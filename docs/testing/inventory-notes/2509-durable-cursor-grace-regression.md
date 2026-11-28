---
inventory-delta:
  packages/maistro-core/tests: +2
---
# 2509-durable-cursor-grace-regression

Round-5 repair for issue #2509, on head `7eacf6ebe4d` (the merged #2544, develop
base `14acce617ce6`). Production sources are unchanged; this round adds the
regression test the issue's oracle 5 demands and the merged change did not have.

**The gap, as executed.** Oracle 5: *"Regression test must FAIL if
`_gap_safe_position` ever again advances past an unresolved hole solely because
`now-first_seen >= grace`."* Every hole test in the merged tree ticks within
milliseconds of the hole opening, so none of them can tell "no timer" from "a
60 s timer". Two out-of-tree copies of the sources, the worktree untouched and
the tests run in place:

- Against the **pre-fix** sources (`cc6776f03f`, grace still in force),
  `test_an_unproven_hole_holds_the_cursor_no_matter_how_long_it_lingers` and the
  PostgreSQL oracle `test_a_hole_a_live_append_may_still_commit_holds_the_cursor`
  both **pass** — the silent-loss behaviour clears the tests named for it. (The
  rollback-crossing and proof tests do fail there, which is why the merge was
  green-sensitive to *that* half.)
- Against the merged sources with the grace **re-introduced beside the proof**
  (`hole not in absent and now - first_seen >= grace → cross`), the whole
  `tests/events` + `test_container_wiring.py` + `test_container_postgres.py`
  battery passes on real PostgreSQL 17: **610 passed, 11 skipped, 0 failed.**

So a timer could come back through `_gap_safe_position` with every gate green —
the exact regression the issue names.

**What changed (tests only, +2 nodes, `packages/maistro-core/tests`).**

- `tests/test_container_wiring.py` (+1):
  `test_elapsed_time_never_authorizes_crossing_an_unresolved_hole`. The module
  that owns `_gap_safe_position` (`maistro.container`) is handed a wall clock
  of its own — its module-level `time` binding, replaced with
  `monkeypatch.setattr(..., raising=False)`, the same technique
  `tasks/test_idempotency_purge_driven.py` and `runs/test_retention_policy.py`
  already use; the global module is left alone so asyncio's loop clock and the
  cursor store's lease timestamps keep running. The clock is turned past 1 s,
  59 s, exactly 60 s, an hour, a day and a year while id 2 stays hidden and
  unproven; the durable position, the log's replay acknowledgement and the
  delivered list must all hold. When the id then appears, the ordinary tick
  crosses it.
- `tests/events/test_container_pg_durable_events.py` (+1): the live-append
  oracle is parametrised over `elapsed_between_ticks` — `[ticks-at-once]` is the
  oracle exactly as merged; `[a-day-between-ticks]` turns the same clock a day
  forward before every tick, so both containers tick *after > grace* with the
  second connection's transaction still able to commit id 2. Lease clocks are
  not touched.

**Demonstrated regression sensitivity (real PostgreSQL 17, both tests).**

| sources | new wiring test | `[a-day-between-ticks]` | `[ticks-at-once]` | `..._lingers` |
| --- | --- | --- | --- | --- |
| merged head `7eacf6ebe4d` | pass | pass | pass | pass |
| head + grace re-introduced | **fail** (`assert 3 == 1`, "after 60s with the hole unproven") | **fail** (`assert 3 == 1` while the append still holds id 2) | pass | pass |
| pre-fix `cc6776f03f` | **fail** (same line) | **fail** | pass | pass |

The two right-hand columns are why this round exists: they are the tests that
were supposed to carry oracle 5 and do not.

**Validation executed this round.** Two dedicated servers started for the job
(`postgres:17`, `pgvector/pgvector:pg18`), `MAISTRO_REQUIRE_PG_LEGS=1`:
`tests/events` + `test_container_wiring.py` + `test_container_postgres.py` =
**612 passed, 11 skipped** on each of PG 17.12 and PG 18.6 (610 before this
round); `tests/migrations/test_event_schema_agreement.py` = 5 passed on both;
without a server the same battery is 526 passed / 97 skipped (the PostgreSQL
legs, by design — the new in-memory test runs there). The proof premise itself
was re-probed on both servers with two independent connections: a transaction
that allocated an id holds a granted `RowExclusiveLock` on `event_log_id_seq`
in `pg_locks` until it commits or aborts; a rolled-back allocation is never
handed out again; with `max_prepared_transactions` raised, a prepared
transaction's lock stays visible (`granted`, `pid` NULL) until
`COMMIT PREPARED`. `ruff check` / `ruff format --check` clean on both files;
`check-suite-inventory.py --suite packages/maistro-core/tests` reported
`expected 19354, collected 19356` before this note and is green with it.

**Residual risks (unchanged by this round, not silent loss).** A reader that
holds `AccessShareLock` on the sequence inside an open transaction (`SELECT
last_value FROM event_log_id_seq`, probed above) makes the proof answer "live
append" and hold
the cursor below a rolled-back hole until that reader ends — liveness only. An
append left idle-in-transaction pins the durable position, and with it dispatch
beyond the first `limit` events above the hole, for as long as it stays open;
that is the trade the issue asks for (never cross what can still commit).
