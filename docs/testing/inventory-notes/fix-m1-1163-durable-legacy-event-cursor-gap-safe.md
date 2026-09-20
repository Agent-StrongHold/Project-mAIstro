---
inventory-delta:
  packages/maistro-core/tests: +8
---
# fix-m1-1163-durable-legacy-event-cursor-gap-safe

Answers the three review findings on the #1163 fix
(`fix/m1-1163-durable-legacy-event-cursor`): the durable cursor could be
persisted past an `event_log.id` PostgreSQL had allocated but not yet
committed, the `consumer_cursors` table existed only in the runtime
`CREATE TABLE IF NOT EXISTS` bootstrap, and ADR-086 did not record the new
cursor contract.

**`maistro.events.processing.process_events_batch`** is `process_events`
with one more output: a `ProcessedBatch` whose `holes` lists the first id
of every run of ids in `(after_id, cursor]` the log did not return.
`process_events` is now a wrapper returning `batch.cursor`, so every
existing caller and test keeps its contract.
**`Container.process_durable_events`** calls the batch form and persists
only what `_gap_safe_position` allows: the position stops just below the
first hole this holder has known for less than
`durable_event_hole_grace_s` (`DEFAULT_HOLE_GRACE_SECONDS`, 60 s); a hole
that outlives the grace is treated as an aborted append and the position
moves past it. Handler work is never delayed, only the persisted resume
point. **`alembic/versions/036_consumer_cursors.py`** is a frozen copy of
the `consumer_cursors` block of `pg_stores._SCHEMA`, checked against it by
the existing catalogue comparison. **ADR-086** gains a dated amendment
recording ownership, lease, fencing, settled-before-persisted and gap
semantics.

**Tests (+8, all in `packages/maistro-core/tests`).**
`tests/events/test_processing.py` gains `HidingLog` (a log whose reads
skip chosen ids, standing in for PostgreSQL between allocation and commit)
and `TestTheBatchReportsWhatTheLogSkipped` (+5): contiguous ids report no
holes; every gap is reported by its first missing id while the visible
events are still processed; a hole at the very start is reported; holes
above an unsettled event are not counted; `process_events` returns the
batch cursor. `tests/test_container_wiring.py` gains (+3)
`test_the_durable_cursor_waits_below_an_id_the_log_has_not_committed`
(the position stops at 1 while id 2 is hidden and reaches 3 once it
appears, with id 2 delivered then and id 3 deduped),
`test_a_hole_that_outlives_the_grace_is_an_aborted_append` (the position
holds across a second tick, then moves past the hole once the grace is
zeroed), and `test_each_hole_gets_its_own_grace` (a lapsed first hole does
not let the position jump past a second, newer one).

`tests/migrations/test_event_schema_agreement.py` now renders revision 036
alongside 004 and compares four tables instead of three (one test renamed,
node-id count unchanged); `test_migration_chain.py`'s expected-table set
and the `test_wiring_creates_the_schema_it_needs` DROP list gain
`consumer_cursors`. Both need a PostgreSQL server and run in CI's
`durable-events` and migration jobs.

`packages/maistro-core/tests/events` + `tests/test_container_wiring.py` +
`tests/migrations` (370 passed, 130 skipped without PostgreSQL) pass.
`ruff check`/`ruff format --check` clean on every touched file;
`mypy --strict` clean on `container.py` and `maistro.events`.
