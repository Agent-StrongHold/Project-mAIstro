# Issue #1572 repair checkpoint — f97534cb

## Frozen scope

- One item: assigned issue #1572, branch `auto-1572` in the assigned worktree.
- Starting HEAD: `4940eb53bbc0e9607dd3c621f4d0395aa38edcda` (verified).
- Dispatch base: `d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743` (resolved by diff).
- Repair targets: actual execution-lifecycle / vulture failures, canonical Goal
  implementation and adjacent tests, relevant migration/production composition
  acceptance, and this report. No remote mutation or unrelated feature repair.
- Initially clean worktree; no incoming edits to salvage.
- Existing branch contains substantial unrelated differences from dispatch base;
  they will not be discarded or repaired speculatively.

## Initial evidence and assumptions

- Read repository AGENTS.md and supplied dispatch issue body.
- Driver logs check-0 through check-4 report dependency sync, lint, formatting,
  Goal tests (55 passed, 16 skipped), and core inventory passing. These are
  supplied evidence only; acceptance validation will be executed independently.
- Previous lifecycle block may still require an already-landed authorization;
  no lifecycle/grant ledger edits are permitted in this lane. The explicit
  exception permits only evidence-based vulture ledger repair.
- Interpret writer assignment as focused repair and local commit, not closure or
  integration approval. No prior result is assumed current.

## Progress

Reproduced results (no production changes):

- CI-exact Vulture command PASS: 1326 reviewed identities / 1326 findings,
  no unclassified findings. No ledger amendment is warranted.
- CI-exact `uv run python scripts/check-execution-lifecycles.py` FAIL:
  trusted merge base `66f3cea9e989`, 19 classified / 20 discovered;
  `maistro.goals.model::GoalStatus` has no already-landed authorization.
  Confirmed command at `.github/workflows/quality.yml:1501`. The script does
  not implement `--help`; that initial invocation also ran the failing gate.
- `uv run pytest tests/test_check_execution_lifecycles.py -x -q`: FAIL,
  28 passed / 1 failed at `tests/test_check_execution_lifecycles.py:374`,
  reproducing the same policy prerequisite.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format
  '{{.ServerVersion}}'`: FAIL, daemon unavailable. Live PostgreSQL acceptance
  cannot be inferred from skipped tests.
- Read previous job result and report; its blocker still reproduces. Do not
  retry the same gate or rename/remove GoalStatus to evade it.
- `origin/develop` resolves to the assigned dispatch base. No current conflict
  exists. No fetch/merge is indicated as conflict repair.
- Inspected Run-binding and SQLite reopen tests: reopen binds revision 2 while
  the Goal remains at revision 2. It does not prove binding preservation across
  later Goal revision advancement. This coverage limitation remains explicit;
  it is not evidence for a production defect or the assigned CI failure.

## Additional executed validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3187 files.
- `uv run pytest packages/maistro-core/tests/goals
  packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py
  -x -q`: 55 passed, 16 skipped.
- `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py
  tests/migrations/test_migration_chain.py -x -q`: 2 passed, 23 skipped.
- `uv run python scripts/check-m1-convergence-freeze.py --base
  d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 15659 unique identities, no duplicates.
- `git diff --check`: PASS.
- Inspected the assigned develop snapshot's authorization JSON via `git show`:
  no `GoalStatus` or `goals.model` match. Syncing to that frozen snapshot does
  not supply the missing authorization prerequisite.

## Architecture reconciliation

Read accepted ADR-081226-a66b, ADR-082826-d9f5, ADR-092326-97c4, and
ADR-091726-7c2a. Goal desired-state lifecycle is not Run execution authority;
Run/NodeRun/Attempt remain canonical. `ScopedGoalStore` delegates to the existing
WorkspaceAuthorizer. Backend wiring refuses an unmigrated configured PG pool
rather than falling back to memory. The interview-before-commit requirement is
upstream consumer orchestration, not a reason to introduce it into this store
repair. No competing authority or ADR change is proposed.

## Acceptance map (this job's evidence only)

| Criterion | Evidence and boundary |
| --- | --- |
| Goal/GoalRevision round-trip on memory, SQLite, PostgreSQL | Shared conformance round-trip passes memory/SQLite; PostgreSQL skipped, so all-three acceptance UNVERIFIED. |
| Append-only revisions, stale revision refusal, exactly one concurrent winner | Shared conformance CAS and lifecycle tests pass memory/SQLite, including terminal finality; PostgreSQL UNVERIFIED. |
| Subgoal parent/Project and recorded Agent change | Shared conformance lineage and reassignment tests pass memory/SQLite; PostgreSQL UNVERIFIED. |
| Run admission binding and immutable historical revision | Admission/terminal-transition binding tests pass memory/SQLite; PostgreSQL and preservation across later Goal revision advancement UNVERIFIED. |
| Workspace isolation; foreign equals missing | Scoped conformance tests pass memory/SQLite through WorkspaceAuthorizer, comparing refusal type/message and mutation results; PostgreSQL UNVERIFIED. |
| Shipped Container exposure and production composition | Actual `create_container` exposure and authorized access tests pass; backend selection/fail-closed tests pass. Product durable restart remains UNVERIFIED. |
| Restart durable composition with Goals/revisions/bound Runs | SQLite close/reopen test passes, but constructs core stores, not a restarted Hive/server process. PostgreSQL/product restart UNVERIFIED. |
| No competing executor or product-private Goal lifecycle | Convergence-freeze PASS; separate execution-lifecycle gate FAIL remains binding. |
| Preserve merged user-model 056 and planner 057 identities/ancestry, append unused migration | Two static installed-base identity/provenance checks PASS; live upgrade matrix UNVERIFIED. |
| Actual populated c560d4c/4675101 snapshot upgrades, data/index/constraint preservation, reopened durable provenance | PostgreSQL tests skipped; UNVERIFIED on both PG17 and PG18. |
| Fresh install, single head/unique IDs, downgrade/refusal/reapplication, earlier supported quota-door ancestry | Static graph/provenance checks pass where exercised; database chain legs skipped. Full supported-history compatibility and both-major matrix UNVERIFIED. |

No tests were added or changed; no inventory delta is required.

## Reachable composition and integration-scope boundary

Confirmed shipped callers at
`packages/hive-conductor/backend/adapters/maistro_core.py:195` and
`packages/maistro-server/src/maistro_server/main.py:344` call `create_container`.
Core selects the Goal backend at `packages/maistro-core/src/maistro/container.py:2362`
and exposes it at line 2648. This is source reachability, not evidence of a
successful deployed durable restart.

Read `.github/workflows/integration-scope.yml`: the gate aggregates specialized
producer checks for the exact candidate, separately from the lifecycle gate.
Inspected the frozen dispatch's captured check-run objects: zero have the exact
assigned HEAD. The cause of the supplied remote `integration-scope: failure`
is therefore UNRESOLVED; attributing it to Vulture or lifecycle would be a guess.

Executed scope classification from measured paths:
`git diff --no-renames --name-only d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743...HEAD`
passed to `uv run python scripts/ci_merge_group_scope.py --json`: all seven
scope flags true. Then executed `uv run python scripts/check-integration-scope.py
--event-name merge_group --scope-json <that computed JSON>`: FAIL, all nine
required results missing (docker-build, durable-events, Hive E2E/backend and UI,
MinIO, PG17, PG18, strike-ladder, wheel-imports). No synthetic success results
were supplied. This establishes incomplete local evidence, not the remote
failure's cause.

## Final disposition

BLOCKED. Only this report changed. No demonstrated Vulture debt exists to bank;
no authorized in-lane edit can supply a trusted-base lifecycle grant. Do not
rename a required domain lifecycle or weaken discovery to evade the gate.

Next prerequisites: the authorized owner must land the GoalStatus lifecycle
policy prerequisite separately; supply exact-candidate specialized producer
failure logs and accessible PostgreSQL services before attempting another CI
repair. No remote mutation, sync, ledger, grant, test, or production edits were
performed. Existing branch work is preserved.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, blocked 1.
This evidence-only handoff is committed locally, not integration approval.
