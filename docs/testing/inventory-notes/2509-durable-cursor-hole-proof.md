---
inventory-delta:
  packages/maistro-core/tests: +19
---
# 2509-durable-cursor-hole-proof

Issue #2509 (M1-E1, P1 silent event loss): `Container._gap_safe_position`
advanced the durable consumer cursor past an unresolved `event_log` id hole
once the hole had been open for `durable_event_hole_grace_s` (60 s) — but a
PostgreSQL transaction can hold an allocated `BIGSERIAL` id past any timeout
and commit it afterwards. Crossing the hole on elapsed time therefore
permanently excluded the late event from every later ``id > cursor`` read,
restart and lease takeover included. The two tests that encoded the assumption
(`test_a_hole_that_outlives_the_grace_is_an_aborted_append`,
`test_each_hole_gets_its_own_grace`) asserted exactly this and are replaced.

**What changed (behaviour).** The durable position now crosses a hole only on
the log's own durable evidence that the hole is *terminally absent*: the
allocating transaction ended without committing and no future transaction can
make the id visible. `EventLogStore` gains `prove_holes_absent`, with three
implementations. PostgreSQL: a transaction that has called `nextval` holds a
granted lock on `event_log_id_seq` until it commits or aborts, so a granted
lock in `pg_locks` means some append may yet commit a hole (prove nothing);
no lock plus a still-invisible id in a fresh read means the append rolled
back, and since a sequence never hands an id out twice, the id is crossed
safely — database evidence, never elapsed time. SQLite: taking the write lock
(`BEGIN IMMEDIATE` under a zero busy timeout) proves no writer transaction is
live, and a re-read inside that lock answers terminally. In-memory: appends
are synchronous and nothing can prove an id absent, so the honest answer
proves nothing and the cursor holds below the hole. `_gap_safe_position` lost
its `now` parameter, its per-holder first-seen map, and
`durable_event_hole_grace_s` / `DEFAULT_HOLE_GRACE_SECONDS` ceased to exist.
ADR-086's gap-policy bullet records the new contract.

**Tests (+14, all in `packages/maistro-core/tests`).**
`tests/test_container_wiring.py` (+1 net): the two grace tests become
`test_an_unproven_hole_holds_the_cursor_no_matter_how_long_it_lingers` (an
unproven hole pins the durable position and the replay acknowledgement across
arbitrarily many ticks — no clock input exists for a grace to consume),
`test_only_durable_evidence_moves_the_cursor_past_a_hole` (the position
crosses exactly the holes the log proves absent and never passes the first
unproven one, via a `_ProvingLog` shim answering `prove_holes_absent` from a
test-controlled set), and
`test_durable_evidence_advances_the_cursor_past_a_rolled_back_append` (a
full `process_durable_events` loop where proof arrives mid-stream and moves
the persisted position without redelivering settled events).

`tests/events/test_durable_store_conformance.py` (+8): the universal
`prove_holes_absent` invariants over all three backends (a visible id is
never absent; proving no holes proves nothing) plus the in-memory honest
refusal; a real two-connection SQLite test on a file database (a live writer
transaction proves nothing, a rolled-back one is proven absent); and a
PostgreSQL two-connection test (gated on `MAISTRO_TEST_DATABASE_URL`):
connection A allocates id 2 and holds its transaction open while the pool has
committed id 3 — the proof comes back empty for as long as A can commit,
then proves 2 absent once A rolls back, and confirms the sequence never
handed 2 out again.

`tests/events/test_container_pg_durable_events.py` (+2, PostgreSQL-gated):
the issue's end-to-end oracles on a real server. One: two independent
connections, A holding id 2 open while id 3 committed — two production ticks
and a lease takeover by a second container all hold the durable cursor at 1;
after A commits, the ordinary path delivers id 2 (once, deduped where
already settled) and the position settles at 3 with id 3 retained. Two: A
rolls back and the next tick crosses the hole on durable evidence — bounded
forward progress, no sleep and no timer.

**Repair round (PR review + SAST gate).** Three follow-ups on the same
change, each with a test that fails against the code it repairs:

1. *Every skipped id is reported, not just the first of a run*
   (`ProcessedBatch.holes`, first review finding): proving hole 2 absent said
   nothing about the ids 3, 4, … behind it — the old first-of-run report let
   `_gap_safe_position` ride 2's proof past ids whose appends may still
   commit. `process_events_batch` now reports every missing id, so each is
   proven on its own and the position stops below the first unproven one.
   `test_every_gap_is_reported_by_its_first_missing_id` asserted the collapsed
   form and is replaced by `test_every_missing_id_of_a_run_is_reported`
   (count-neutral), and `tests/test_container_wiring.py` gains
   `test_proof_of_one_hole_never_crosses_the_unproven_ids_behind_it` (+1):
   ids 2 and 3 hidden while 4 is readable, only 2 proven — the tick settles
   4 but the position stops at 2 until 3's proof arrives, then moves to 4.
2. *The SQLite proof runs on an isolated connection* (second review
   finding): `_wire_sqlite_durable_events` wires all four durable stores onto
   ONE connection, so a proof that took its write lock on the shared spine
   connection would roll back a sibling store's uncommitted INSERT while the
   sibling still reported success. `prove_holes_absent` now opens its own
   connection to the same file (`BEGIN IMMEDIATE` answers database-wide, so
   the instance lock was never the guard); a pathless `sqlite://` (in-memory)
   cannot isolate, so it honestly proves nothing. `test_durable_store_conformance.py`
   gains `test_the_sqlite_hole_proof_never_rolls_back_a_sibling_stores_write`
   (+1): it fires a sibling `trigger_definitions` INSERT into the exact
   window that loses it — between the proof's re-read and its rollback — and
   asserts the row survives the commit; against a shared-connection proof the
   row is gone.
3. *SAST / Bandit gate*: the `# nosec B608` annotation for the hole re-read
   sat on its own line above the f-string bandit flags, so `SAST / Bandit`
   failed with one Medium B608 finding; it now annotates the flagged line
   itself (same placement as the other in-file `nosec`), and the gate is
   back to a strict 0 Medium+ baseline. `aiosqlite` is imported at the
   proof site, not at module scope: a top-level import made `import
   maistro_server.main` — and with it the wheel-imports, image-smoke and
   registry gates — require the optional `sqlite` extra in environments
   that never open a SQLite store, so the function-local runtime import is
   the final wiring (the constructor's annotation stays a string under
   `from __future__ import annotations`).

**Demonstrated regression sensitivity.** All three repair-round tests fail
against the pre-repair head `5202e6b082` (collapsed `holes`, shared-connection
proof) and pass with the repair; against the pre-fix sources the original
evidence-gated tests fail while the old grace test passed, i.e. it was green
precisely on the behaviour the issue calls silent event loss.

**Repair round 4 (Coverage gate / diff coverage).** The quality workflow's
`Coverage gate (publish-set floor + diff coverage)` failed at `9726d3600a`
(PR run 46009688857, job 140551723921) with
`packages/maistro-core/src/maistro/events/durable_log.py: 75.0% of 8 changed
branch arcs (need 80%); partial at 504, 505` — the two uncovered arcs are
`_database_path`'s defensive branches: the loop iterating past a non-`main`
row and the loop exhausting without one. Both are unreachable against a real
aiosqlite connection, whose `PRAGMA database_list` always lists `main` first
(verified against the engine: `(0, 'main', <file>)` even with a database
attached), so no test over a live store could ever take them and the per-file
branch floor failed. The repair adds five tests to
`test_durable_store_conformance.py` (+5 collected node IDs, recorded above):
a real-connection test with a database attached (pins `main`-row-zero and the
row shape the proof relies on), a stub test proving selection is by row NAME
not list position (an engine that listed an attached database first would
otherwise send the isolated proof connection to the wrong file), and three
parametrized refusals — no `main` row, `main` with an empty file column, and
`main` at `:memory:` — each asserting `_database_path()` answers None AND
`prove_holes_absent` proves nothing, the contract that keeps the proof from
opening an isolated connection to some other, empty database. Sensitivity
proven by mutation, both reverted byte-identically afterwards: resolving by
position instead of name fails 2 of the 5 (the no-main-row refusal and the
name-selection test), and dropping the `:memory:` refusal fails exactly the
`main-in-memory` case. With the repair, the gate script at CI's exact argv
(`uv run python scripts/check-diff-coverage.py coverage.xml --base
c2beba3f81…`) reports `ok: every measured file this change touches is at or
above 90% lines / 80% branch arcs` over a coverage database that measures
both the SQLite legs and the PostgreSQL legs (docker `pgvector:pg17`,
`MAISTRO_REQUIRE_PG_LEGS=1`: 602 passed, 4 skipped — the same combined
producer data CI's gate reads). The `tests/events`+`test_container_wiring.py`
battery is 258 passed / 79 skipped.

**Legs.** `packages/maistro-core/tests/events` + `tests/test_container_wiring.py`
with `MAISTRO_TEST_DATABASE_URL` pointing at a real PostgreSQL (docker
`postgres:17`), `MAISTRO_REQUIRE_PG_LEGS=1`: `packages/maistro-core/tests/events`
525 passed (5 skips are purge/envelope legs gated on other stores or
`MAISTRO_TEST_PG_DSN`), `tests/migrations/test_event_schema_agreement.py`
5 passed, full `packages/maistro-core/tests` 18085 passed / 1179 skipped with
only `workspaces/test_sqlite_alembic_schema_parity[postgres]` failing — a
pre-existing environment limitation (plain postgres:17 cannot serve the
alembic chain's `CREATE EXTENSION vector`; CI runs that leg on the pgvector
image) reproduced identically on untouched `5202e6b082`. CI-exact
`uv run bandit -r packages/maistro-core/src packages/hive-conductor/backend
packages/maistro-server/src -ll --confidence-level=medium`: 0 Medium+.
Mypy clean on `events` and `container.py`; Ruff check + format clean;
`check-suite-inventory.py --suite packages/maistro-core/tests` green at the
recorded +14.
