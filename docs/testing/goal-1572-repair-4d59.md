# Goal store #1572 repair checkpoint (4d59)

## Frozen scope and assumptions

Only issue #1572, assigned branch `auto-1572`, initial clean HEAD
`6d7458151b6224ac331c09f61514a8e6095f8f0c`, supplied develop base
`e46ad6708fda20f76b8915679ef701f3ddb6b7e2`. No remote refresh or mutation.
The supplied dispatch snapshot is the sole issue/PR snapshot. Explicit repair
assignment selects writer mode over the generic verifier instruction.

Frozen inspection scope: the existing Goal implementation and adjacent Run,
Container, authorization and migration paths/tests; relevant accepted ADRs;
the named integration-scope, execution-lifecycle and vulture gate configuration;
the supplied five check logs and prior result. Potential edits are limited to
an evidenced Goal repair, its tests/inventory note, the expressly permitted
vulture ledger if warranted, and this report. No other ledger/grant changes.

## Initial evidence

Read dispatch issue acceptance and prior result, and inspected all five supplied
check logs: sync/lint/format pass; Goal/parity tests report 55 passed, 16 skipped;
core inventory reports 15,797 identities. Skips are not PostgreSQL acceptance.
Existing Goal model retains domain lifecycle separate from execution; historical
reports claim a missing trusted-base GoalStatus authorization. That claim will
be re-executed, not assumed. No salvage needed; worktree was clean.

## First-hand gate checkpoint

- CI-exact vulture invocation passed: 1,326 reviewed identities, 1,326 findings;
  no unbanked identities, so no ledger amendment is justified.
- `uv run python scripts/check-execution-lifecycles.py` failed: GoalStatus is
  absent from trusted base `e46ad6708fda` without already-landed authorization
  (19 classified -> 20 discovered). The base is now the actual merge base and
  local `origin/develop`; another merge of that same ref cannot fix this.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format
  '{{.ServerVersion}}'` failed: cannot connect to daemon. PostgreSQL legs remain
  unavailable unless an existing configured service is found.

Read accepted ADR-081226-a66b, ADR-082826-d9f5, ADR-092326-97c4 and
ADR-091726-7c2a. Preserve one canonical execution/store/Workspace authorization
path; interview orchestration remains consumer scope. No conflicting issue
instruction warrants a new execution authority or policy bypass.

Integration Scope aggregates specialized producers, not the lifecycle gate.
The lifecycle failure must not be presented as the cause of the remote
integration-scope failure. Its exact-candidate evidence will be checked only
in the frozen dispatch snapshot.

## Executed validation

All commands ran in the assigned worktree with 1,200-second command timeouts.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,326/1,326 |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL, missing trusted-base GoalStatus authorization |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,205 files |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` | 55 passed, 16 skipped |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed at line 374, same policy failure |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q` | 2 passed, 23 skipped |
| `uv run python scripts/check-m1-convergence-freeze.py --base e46ad6708fda20f76b8915679ef701f3ddb6b7e2` | PASS |

The frozen dispatch contains 30 exact-head check records. Unlike the prior job,
there IS exact-head evidence here: `exact-debt-ledger` succeeded, Quality gate
failed, and `integration-scope` was still in progress at capture. All nine
specialized producers were queued/in progress, not successful. Therefore the
reported later integration-scope failure's cause remains UNRESOLVED; no remote
log was invented or refreshed.

Computed scope from `git diff --no-renames --name-only
 e46ad6708fda20f76b8915679ef701f3ddb6b7e2...HEAD`, passed those paths to
`uv run python scripts/ci_merge_group_scope.py --json`: all seven flags true.
Executed `uv run python scripts/check-integration-scope.py --event-name
merge_group --scope-json <computed JSON>` without fabricated results: exit 1,
missing docker-build, durable-events, Hive backend/UI E2E, MinIO, PostgreSQL
17/18, strike-ladder and wheel-imports. This demonstrates missing local
producer evidence, not the cause of the remote failure.

## Production reachability and acceptance map

Source inspection: server `packages/maistro-server/src/maistro_server/main.py:344`
and Hive `packages/hive-conductor/backend/adapters/maistro_core.py:195` call
`create_container`; core `container.py:2362` selects the Goal store and line
2648 exposes it. `goal_reader` delegates to `ScopedGoalStore`, which uses the
canonical `WorkspaceAuthorizer`. Configured PostgreSQL missing Goal tables
fails closed in `goals/wiring.py`, covered by the executed wiring tests.
This is source reachability plus focused Container execution, not a claim
that both shipped services were restarted.

| Acceptance | Current evidence / limitation |
| --- | --- |
| Goal/GoalRevision round-trip on all three backends | Shared conformance passed memory/SQLite; PostgreSQL skipped: all-three UNVERIFIED. |
| Append-only revisions, stale refusal, one concurrent winner | Executed shared conformance covers append/CAS and terminal transitions in memory/SQLite; PostgreSQL UNVERIFIED. |
| Subgoal parent/Project, recorded Agent reassignment | Executed shared conformance covers lineage rejection and attributed reassignment; PostgreSQL UNVERIFIED. |
| Run admission and immutable historical binding | Executed `test_run_goal_binding.py` covers admission payload, terminal transition preservation and half-binding refusal in memory/SQLite. Later Goal revision advancement is not exercised; PostgreSQL and that stronger historical case UNVERIFIED. |
| Cross-Workspace read/write isolation; foreign equals missing | Executed shared scoped conformance through WorkspaceAuthorizer in memory/SQLite; PostgreSQL UNVERIFIED. |
| Shipped Container exposes store; both production compositions | Executed real Container exposure and authorized create/read/refusal tests; both production callers inspected as above. Durable Hive/server startup/restart UNVERIFIED. |
| Durable Goal/revision/bound Run restart readback | SQLite connection close/reopen test passed; it is fresh stores, not product process restart. Goal stays at bound revision 2, so later-revision history is UNVERIFIED. |
| No second execution authority | Convergence freeze passed. Domain Goal lifecycle is separate from Run/NodeRun/Attempt, but its policy authorization gate still fails. |
| Preserve merged user-model 056 and planner 057 ancestry; append unused Goal identity | Executed static migration identity/provenance tests passed; Goals append at 062 after HITL 061. External allocation coordination UNVERIFIED. |
| Actual c560d4c/4675101 populated forward upgrades with user-model/Run/index preservation, Goal tables/readback and immutable provenance | Live tests skipped; UNVERIFIED for PostgreSQL 17 and 18. |
| Fresh install, single-head/unique IDs, downgrade/refusal, reapplication, older quota-door histories | Static revision graph covered by passing identity test; database legs skipped, compatibility matrix UNVERIFIED for both majors. |

## Disposition

**BLOCKED.** No evidenced vulture defect exists to repair. Lifecycle policy
requires a separate, already-landed trusted-base authorization; this lane
cannot edit that grant or ledger or weaken the gate. The starting branch
already contains the supplied develop base, so no sync conflict exists to
resolve. Required specialized CI producers have no successful completion in
the frozen snapshot. Docker is unavailable, leaving PostgreSQL acceptance
unexecuted.

Changed file: only `docs/testing/goal-1572-repair-4d59.md`. No tests, code,
workflow or ledgers changed; no test inventory delta is needed. Existing work
is preserved. This report is committed locally as a blocked handoff, not
integration approval. No GitHub mutations or destructive git operations.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 policy blocker.
Next: authorized owner lands the policy prerequisite separately; supply
completed exact-candidate specialized CI logs and accessible PostgreSQL 17/18
services, then revalidate the explicitly unverified criteria.
