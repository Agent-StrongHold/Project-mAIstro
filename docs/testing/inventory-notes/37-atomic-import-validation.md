---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Validation record for the #37 atomic initial-roster follow-up

Companion to `37-atomic-import-roster.md` (the test-count delta lives there:
`packages/maistro-core/tests` +15, `packages/hive-conductor/backend/tests` +2;
this note adds no tests). Everything below was executed in worktree
`/home/dev/Git/wt/auto-37` against a real PostgreSQL 18 instance
(`MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:5433/auto37`,
migrated with `alembic upgrade head` through 069).

## Failing-before / passing-after

Candidate diff = working tree over `a4acfa8424` (the preserved authority-fence
commit). A detached scratch worktree at `a4acfa8424` with only the two new
test files copied in was used for the failing-before leg, then removed.

- Before (at `a4acfa8424`, scratch worktree): 17/17 new node IDs fail —
  `TestInitialRosterIsPartOfCreation` (15: `create()` rejects the
  `initial_memberships` kwarg) and
  `test_first_import_cannot_replay_a_revocation_after_canonical_create`
  (sqlite+postgres) fails at
  `assert not await workspace_authority.is_member("bob", workspace_id)` →
  `assert not True`, i.e. the concurrent revocation was actually overwritten
  by the post-commit roster replay.
- After (this tree): the same 17 node IDs pass (memory/sqlite/postgres).

## Commands and outcomes

- `uv run pytest packages/maistro-core/tests/workspaces/
  packages/maistro-core/tests/tasks/test_admission.py
  packages/maistro-core/tests/tasks/test_workspace_routing.py
  packages/maistro-core/tests/persistence/test_workspace_orphan_disposition_migration.py
  packages/maistro-core/tests/persistence/test_workspace_scope_fence_pg.py
  packages/hive-conductor/backend/tests/test_workspace_authority*.py
  packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py
  packages/hive-conductor/backend/tests/test_manual_fire_canonical.py`
  with PG DSN → **603 passed, 2 skipped** (the skips are the documented
  single-writer interleavings at
  test_workspace_store_conformance.py:455).
- Without DSN → 124-node scoped run passed; 56 passed / 31 skipped
  (conformance), 19 passed / 11 skipped (durable), 9 passed (authority unit).
- `uv run ruff check .` → clean; `uv run ruff format --check .` → clean
  (one test file needed reformatting; reformatted).
- `uv run mypy packages/maistro-core/src` → Success, 846 files.
- `uv run python scripts/check-suite-inventory.py` → ok: 21 suites match the
  recorded inventory (roster note delta reconciles).
- `uv run python scripts/check-ac-state.py` → exit 0 (report-only).
- `uv run python scripts/check-adr-index.py` → OK.

## Remaining issue-wide acceptance gaps (not claimable here)

- The issue closure gate wants an exact candidate SHA, CI link, and AC-by-AC
  evidence on the merged PR; this record is local validation only.
- The Turing backend's private per-process `InMemoryWorkspaceStore` and the
  joint #1419 representation-purpose audit remain open, as recorded in the
  updated ADR limitations section.
- Full-repo `uv run pytest` was not run (≈34 collection errors without all
  services up, per repo guidance); scope-limited runs above cover every
  touched package's suites.
