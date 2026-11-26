---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# #72 repair round: #1157 evidence re-proof and stale develop-sync block

## Why this round exists

The prior verifier round at head `f6082ea80a` reported: "Child issue #1157 is
not addressed in the current branch (no commit messages contain #1157)". That
finding was produced by a commit-message/events-log text scan and is
contradicted by the tree contents. This round re-proves the criterion from
reachable production behavior and executed tests, and records the result so the
evidence is discoverable by any future scan.

## #1157 (serialize SQLite ensure_schema upgrades across processes) — addressed

- Production mechanism: `packages/maistro-core/src/maistro/sqlite_schema.py`
  defines `serialized_schema_upgrade` (async) and `serialized_schema_upgrade_sync`.
  Both take SQLite's database write lock via `BEGIN IMMEDIATE` before any
  read-then-DDL sequence, raise `PRAGMA busy_timeout` to 60s for the upgrade
  (restored afterwards), keep DDL transactional so a failed upgrade rolls back
  as one unit and can be retried, and roll back on a failed `COMMIT` so the
  write lock is never leaked.
- Wiring: the context managers are imported by the SQLite `ensure_schema` of the
  four legacy persistence families (`sqlite_audit`, `sqlite_episodic`,
  `sqlite_learnings`, `sqlite_outcomes`, `sqlite_prompts`, `sqlite_quota`,
  `sqlite_sessions`) plus runs/workspaces/projects/scheduling/events/capabilities
  stores and the durable-run stores (23 importing modules).
- Tests: `packages/maistro-core/tests/persistence/test_sqlite_schema_concurrency.py`
  (in-process, two connections racing one file) and
  `packages/maistro-core/tests/persistence/test_sqlite_schema_upgrade.py`
  (fork-based cross-process workers over the legacy schema shapes, plus
  rollback-and-retry, configured-wiring failure propagation, and a legacy
  capability-invocation column upgrade; 9 test functions).
- Executed evidence (this head): both files together with the quota usage-log,
  elevation-durable, and container-wiring suites → `72 passed, 3 skipped`.

## Prior "develop sync conflict preserved in worktree" block — stale, nothing to resolve

`git fetch origin` then inspection: `origin/develop` tip `b43175c1d` is exactly
`git merge-base HEAD origin/develop`; `git rev-list --count origin/develop ^HEAD`
is 0. The develop tip is already merged into `auto-72` (merge `dafba0f46`) and
the worktree is clean. No conflict exists to resolve.

## Additional acceptance validation executed this round

- `ruff check .` and `ruff format --check .` — clean.
- `packages/maistro-server` health/main/strike-health suites → `48 passed`.
- Suite inventory gates for `packages/maistro-core/tests` (11471) and
  `packages/maistro-server/tests` (422) — match.
- Against a real empty PostgreSQL 18 (`auto-72-verif-pg`, port 18790):
  `tests/migrations/test_migration_chain.py` → `12 passed` in 68s, proving the
  alembic chain including the renumbered `045_durable_elevation_grants`
  migration applies cleanly to a clean machine.
- With `MAISTRO_TEST_PG_DSN` on the migrated database:
  `test_pg_strikes.py`, `test_strike_recovery.py`,
  `test_strike_tracker_conformance.py` → `83 passed, 19 skipped` (#1172
  reversible-lockout semantics against real PG).
- Without the DSN the whole `packages/maistro-core/tests/persistence/` suite →
  `494 passed, 171 skipped`.

## Known-environment limitation (not a regression)

With `MAISTRO_TEST_PG_DSN` set, a subset of persistence conformance files
(e.g. `test_pg_learnings.py`, `test_thumbs_conformance.py`) fail at pytest
fixture setup with a pytest-asyncio loop-scope runner error. The identical
error pattern reproduces on `origin/develop` (`b43175c1d`) in a throwaway
worktree, so it is a pre-existing trunk test-wiring issue, not introduced by
this branch. Out of scope for this repair; recorded for a future test-infra
round.
