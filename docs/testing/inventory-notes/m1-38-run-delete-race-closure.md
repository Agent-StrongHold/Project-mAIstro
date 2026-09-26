---
inventory-delta:
  packages/maistro-core/tests: +3
---
# m1-38-run-delete-race-closure

The 2026-09-08 foundation review's second finding, reproduced and closed. The
reproduction (forced deterministically, never by hoping the event loop
interleaved): `SqliteProjectScopeStore.delete` answered its Run-ownership
SELECT ("no Runs"), a `SqliteRunStore.create_run` on the same connection then
validated the still-present Project and committed its Run, and the released
delete removed the Project -- both operations reporting success, the Run
permanently filed under a Project that no longer existed.

Root cause: two private `asyncio.Lock`s over one shared connection. Each store
serialized itself; nothing serialized the cross-store check-then-act pair.
`create_run` also opened its transaction at the INSERT, not before its scope
validation read, so a second process sharing the file had the same window.

Fix (production code, `maistro-core`):

- `connection_write_lock` in `maistro.sqlite_schema` -- the per-connection
  lock `serialized_schema_upgrade` already keys schema work by, exposed for
  data writes. Both `SqliteProjectScopeStore` and `SqliteRunStore` now take
  it, so the delete's ownership check and the create's validation+INSERT are
  one in-process critical section. This is the same "exactly one lock per
  connection" rule `SqliteWorkspaceStore` already follows for `create_root`.
- `SqliteProjectScopeStore.delete` runs every refusal (Run ownership
  included) inside `_serialized_write`, so the reads that decide precede the
  DELETE under `BEGIN IMMEDIATE`.
- `SqliteRunStore.create_run` opens `BEGIN IMMEDIATE` *before* the scope
  validation read -- #1147's rule applied to the Run side -- and rolls back
  at a single boundary on every failure path (the previous inner
  rollback-then-raise is preserved by moving it to that boundary).

Tests added (`tests/projects/test_run_delete_race.py`), each forcing the exact
interleaving with events and each verified to fail against the pre-fix code
(all three fail with the fix reversed via `git apply -R` of the source patch;
all three pass with it applied):

1. delete paused inside its ownership check -> `create_run` is blocked on the
   shared section (asserted before release, structurally, not by timing),
   then refuses the now-deleted Project; no orphan.
2. `create_run` paused inside its scope validation (one-shot hook, so the
   delete's own `_require` -> `get` is not what blocks) -> the delete waits,
   then finds the committed Run and refuses `ProjectNotEmpty`.
3. Two connections to one file (the cross-process form): the delete side
   holds SQLite's write lock from its ownership read onward; the create
   side's `BEGIN IMMEDIATE` parks behind it and then validates against
   committed state; a third connection confirms zero Runs for the deleted
   Project.

Why the other legs need no new test here: the in-memory store's ownership
predicate and `get` never suspend (no aiosqlite worker thread), so
single-event-loop atomicity holds by construction -- the doctrine the
conformance suite already states for it; PostgreSQL wraps delete's checks and
DELETE in one `conn.transaction()` and backs the create side with migration
010's foreign key on `canonical_runs.project_id`. Both remain covered by the
existing three-leg suites (`test_scope_store_conformance.py`,
`test_spine_conformance.py`), re-run green with the PG legs required
(`MAISTRO_REQUIRE_PG_LEGS=1`).
