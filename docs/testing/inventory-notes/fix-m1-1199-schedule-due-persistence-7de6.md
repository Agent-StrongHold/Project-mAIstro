---
inventory-delta:
  packages/maistro-core/tests: +15
---
# fix-m1-1199-schedule-due-persistence-7de6

Fifteen new behavioral tests for the two canonical-store defects named in
#1199; nothing was removed or moved. Six are in
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
