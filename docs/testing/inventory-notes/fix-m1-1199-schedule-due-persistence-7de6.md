---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +31
---
# fix-m1-1199-schedule-due-persistence-7de6

Thirty-one new behavioral tests for the canonical-store defects named in
#1199, plus one Hive test; nothing was removed or moved. The owner's three
SQLite commit/cancellation tests are recorded in
`1304-schedule-transaction-failures.md`, not here. Six are in
`packages/maistro-core/tests/scheduling/test_admission.py`
(`TestTheDueCursorIsRecordedWithoutAFire`): a schedule created just after
the hour stops being selected by `due()` after its first evaluation and is
selected again exactly at the occurrence it recorded; that occurrence still
fires once, on time, from the recorded cursor; an evaluation that learned
nothing new does not rewrite the row; a `BUFFER_ONE` occurrence held behind
an active Run keeps the schedule due, on both the nothing-fired and the
one-fired paths; and a disabled schedule records nothing. The pre-existing
`test_nothing_due_records_no_fire` gained two assertions (the fire count is
untouched and the due cursor is stored) but is not counted. Nine are
parametrized store conformance cases in `test_store.py` counted per backend:
`record_fire(fired_at=None)` moving only the due cursor on memory, SQLite and
PostgreSQL (three), eight same-store callers racing one cursor without a lost
increment on the same three backends (three), plus three SQLite-only cases:
a `put` paused mid-commit while `record_fire` starts, proving every writer
shares the one `BEGIN IMMEDIATE` critical section; two connections to one
file racing `record_fire` without a lost increment; and a write that raises
inside the critical section rolling back and leaving the next writer able to
begin. The PostgreSQL legs skip without `MAISTRO_TEST_PG_DSN` and are collected
by quality.yml's PostgreSQL coverage producer, not ci.yml's pg17/pg18 jobs.

The Codex review of the first head added sixteen more. Twelve are store
conformance cases in `test_store.py`, four per backend: `put` on an existing
row keeps the cursors `record_fire` wrote and returns the row as stored; a
`put` that changes the recurrence clears `next_due_at` so `due()` re-evaluates
it; a `put` of a new row stores the supplied cursors; and
`record_fire(fired_at=None)` with `fires` omitted counts no fire, while a
consumed occurrence with it omitted counts one. Two are SQLite-only: a
schedule store on its own connection waits at SQLite's write lock for a
sibling paused between DML and commit and the sibling's row survives, and
the contrast on a shared connection, where `BEGIN IMMEDIATE` fails inside
the sibling's transaction. One replaces the blocked-commit test's shape in
`test_sqlite_schedule_write_failures.py` and one is new there: a cancelled
writer holds the cancellation until the queued COMMIT resolves, then either
rolls back (the commit failed) or keeps the landed write with no rollback
chasing it. One in `tests/runs/test_wiring.py` proves the spine wires the
schedule store on the `schedule_conn` it is given and falls back to `conn`
without one. The existing container-ownership test gained the third
connection's assertions but is not counted. The Hive test
(`test_scheduler.py`) proves a fire recorded after the row was read survives
`_definition_for`'s refresh.
