---
inventory-delta:
  tests/: 0
  packages/maistro-core/tests: 0
---

# #1572 — salvage the assigned develop merge

Snapshot: assigned issue #1572 only, branch `auto-1572`, starting HEAD
`808c3e5b76d7fdc0e7617a5ba2fdc8646016fa9d`, inherited MERGE_HEAD / assigned
base `34795962548a33f6b6f7e1234dcea201a9df96ef`. The incoming staged and
unstaged diffs were preserved outside the worktree as `../incoming-1572-index.patch`
and `../incoming-1572.patch` before editing. No incoming work was discarded.

Driver logs `check-1.log` / `check-2.log` in job
`3eebb02243aa4470b3ec78adf5834854` reproduce conflict-marker parse errors in
`tests/migrations/test_capability_invocation_effect_index_migration.py`.
The resolution preserves develop's effect-scope schema in migration 035 and
absence of superseded standalone 043/045, while retaining the Goal branch's
single head 061 and unchanged installed user-model 056 / planner 057 identities.
No tests are added or removed; the existing chain guard is reconciled.

Read accepted ADR-081226-9944, ADR-081226-a66b, ADR-087,
ADR-082426-2192, and ADR-092326-97c4. No competing execution, authorization,
or Goal authority is introduced. Database compatibility is not established by
merely changing a head assertion; live installed-base upgrade evidence remains
required.

Initial executed evidence:

- Exact requested vulture command passes: 1326 findings, zero unclassified.
  No speculative whitelist or ledger edits are warranted.
- `uv run python scripts/check-execution-lifecycles.py` fails: GoalStatus has
  no already-landed trusted-base authorization. No grant or lifecycle ledger
  is changed in this repair; this is not repairable by self-authorization.
- Docker with `DOCKER_HOST=unix:///var/run/docker.sock` cannot connect to the
  daemon. PostgreSQL validation is not inferred from skipped tests.
- `/tmp` has no free inodes. Use a worktree-local temporary directory for
  validation instead of deleting anybody else's temporary files.

## Focused validation before merge commit

All Python commands used `uv run`; temporary files used
`TMPDIR=$PWD/.venv/1572-validation/tmp` because the shared `/tmp` inode pool
is exhausted. Logs are retained in `.venv/1572-validation/` (ignored).

- `uv sync --locked --extra dev`: passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3180 files).
- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q`:
  **55 passed, 16 skipped**.
- `uv run pytest tests/migrations -x -q`: **38 passed, 125 skipped**.
- `uv run pytest tests/test_check_execution_lifecycles.py tests/test_check_integration_scope.py -q`:
  **52 passed, 1 failed**. The real-repository lifecycle test fails at
  `tests/test_check_execution_lifecycles.py:374` for the same missing GoalStatus
  trusted-base grant. Integration-scope unit tests pass; that does not establish
  the actual candidate's remote CI producers succeeded.
- `uv run alembic heads`: **061 (head)**, with no duplicate warning.
- `git diff --check`: passed.

The driver reproduced invalid syntax before resolution. The reconciled existing
migration guard now executes, checking both the integrated ancestor set and the
absence of superseded 043/045; adjacent schema-conformance and installed-identity
checks pass without introducing or removing test cases.

## Acceptance map and remaining boundaries

- Round-trip, append-only/stale CAS/concurrent single winner, Subgoal/Project
  lineage, recorded ownership change: shared conformance suite passes for memory
  and SQLite; PostgreSQL **UNVERIFIED** (skipped).
- Foreign/missing authorization equivalence: same suite and real Container seam
  tests pass for memory/SQLite, through `WorkspaceAuthorizer`; PG **UNVERIFIED**.
- Run binding: actual `admit_direct_work` tests pass on memory/SQLite, preserving
  provenance through terminal Run transitions. The existing restart test does
  not advance the Goal revision after Run admission, so that specific historical
  revision scenario remains **UNVERIFIED**, not implied by its assertion message.
- Container: shipped `create_container` exposure and fail-closed backend-selection
  tests pass. Inspected real callers: server `main.py:344`, Hive
  `adapters/maistro_core.py:195`; factory wires Goals at `container.py:2362`.
  Both deployed process compositions/restarts remain **UNVERIFIED**.
- Restart: SQLite stores close/reopen and retain Goal/revisions/Run binding.
  This is not a deployed Hive/server process restart or a live PG restart.
- Migration: offline single-head, original 056/057 byte identities and schema
  parity pass. PG17/PG18 actual-snapshot upgrades, fresh install,
  downgrade/refusal/reapplication, older quota-door history compatibility, and
  central reservation of 061 remain **UNVERIFIED**.

No vulture ledger change is needed: the exact requested scan is already green.
No lifecycle authorization is present in the candidate authorization file either;
editing it here would not authorize this PR and is prohibited. The inherited
merge is finished against the frozen assigned base, not a moving develop tip.
Final merged-head gates are recorded below.
