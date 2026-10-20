# Goal #1572 repair checkpoint — a95abc11

## Frozen scope and disposition

Only issue #1572 in `/home/dev/Git/wt/auto-1572`, branch `auto-1572`.
Starting HEAD: `5d1597934d640bc598613ef922788b5556d73512`.
Assigned develop base: `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`.
The initial worktree was clean; these two commits have identical trees.
Dispatch and driver logs were read from job
`/home/dev/maistro/jobs/a95abc11e1e44d8394b53818c5e58790`;
no GitHub state was fetched or mutated.

**BLOCKED.** The reported lifecycle policy failure still reproduces. The
explicitly requested vulture scan passes with no unbanked identities. No
source change or vulture ledger amendment is justified by this evidence.
Renaming/removing GoalStatus to evade the lifecycle gate would not be a repair.
Grant and non-vulture ledger edits are prohibited in this lane.

Root instructions and accepted ADRs `ADR-092326-97c4` (shared PostgreSQL
Workspace authority) and `ADR-081426-1f7c` (mechanics-only ExecutionRuntime)
were read. No competing authority, scheduler, lifecycle or authorization seam
was introduced. Goal authorization delegates to WorkspaceAuthorizer; backend
wiring refuses an unmigrated PostgreSQL pool instead of falling back to memory.

## First-hand validation

Commands below ran against the starting HEAD, with long timeouts. Outputs are
`repair-*.log` in the job directory. Driver results were inspected but are not
substitutes for these reruns.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,326 reviewed identities / findings; zero unclassified. No ledger change warranted. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL: 19 classified / 20 discovered; `maistro.goals.model::GoalStatus` lacks already-landed authorization at trusted base `e46ad6708fda`. |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed at line 374; reproduces the same policy failure. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q -rs` | 55 passed, 16 PostgreSQL-dependent skips. |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q -rs` | 2 passed, 23 PostgreSQL-dependent skips. Historical-byte identity test actually passed, not skipped. |
| `uv run python scripts/check-m1-convergence-freeze.py --base e46ad6708fda20f76b8915679ef701f3ddb6b7e2` | PASS, no unapproved new architecture island. Initial invocation without required `--base` was rejected, not counted as a pass. |
| `uv run python scripts/check-integration-scope.py --event-name pull_request` | FAIL CLOSED: nine missing specialized producer results. No success results were fabricated. This diagnostic does not establish that those producer jobs themselves failed. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS, 3,205 files formatted. |
| `uv run alembic heads` | PASS, single head `062`. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL: cannot connect to Docker daemon. |

The integration aggregator requires docker-build, durable-events, Hive backend
and UI e2e, MinIO, PostgreSQL 17 and 18, strike-ladder and wheel-imports results.
Those producer results are unavailable locally; the remote integration-scope
failure is not repaired or explained solely by the local lifecycle failure.

## Criterion-to-evidence map

| Acceptance criterion | Executed evidence / remaining boundary |
| --- | --- |
| Goal and GoalRevision round-trip on all three backends | Shared conformance test `test_goal_round_trips_through_the_backend` passes for memory/SQLite. PostgreSQL skipped: UNVERIFIED. |
| Append-only revisions, stale update refusal, one concurrent winner | Shared conformance `test_goal_revision_chain_is_append_only_with_one_cas_winner`, lifecycle and concurrent transition tests pass for memory/SQLite. PostgreSQL UNVERIFIED. |
| Subgoal parent/Project lineage; explicit recorded Agent ownership transition | Shared conformance lineage/reassignment tests pass for memory/SQLite, including invalid parent scope and recorded old/new owner. PostgreSQL UNVERIFIED. |
| Run admission binding and immutable historical revision | `test_run_goal_binding.py` passes admission/terminal transition binding checks for memory/SQLite; half-binding refusal and explicit-only Goal terminalization pass. PostgreSQL UNVERIFIED. Preservation when the Goal advances *after admission* is not exercised by the executed tests: UNVERIFIED. |
| Two Workspace principals cannot read/mutate foreign Goals; foreign equals missing | Shared scoped conformance tests pass for memory/SQLite through WorkspaceAuthorizer. PostgreSQL UNVERIFIED. |
| Production Container exposes store; both shipped compositions | `test_goal_wiring.py` exercises real `create_container`, authorized creation/read/refusal, SQLite backend selection and fail-closed PG schema probes. Live Hive/server durable startup/restart UNVERIFIED; schema probe doubles are not live PostgreSQL evidence. |
| Restart durable composition and read Goal/revisions/bound Run | `test_goal_restart_readback.py` passes SQLite close/reopen. It constructs stores directly, not both deployed products; PostgreSQL and deployed Hive/server restart UNVERIFIED. |
| No GoalRun/second executor/private Goal lifecycle | Convergence freeze passes against the assigned base. Separate lifecycle policy gate still fails; freeze success does not override it. |
| Preserve merged user-model 056 and planner 057 meaning/ancestry; append unused coordinated identity | Two static installed-base tests pass, including exact historical bytes; Goals are 062 after 061, single head. Central reservation/coordination UNVERIFIED. |
| Populated actual c560d4c and 4675101 forward upgrades without reset/restamp | Live historical snapshot upgrade tests skipped. PostgreSQL 17 and 18 UNVERIFIED. |
| After each upgrade: three Goal tables usable, facts/keys/Run data survive, planner artifacts/head preserved, durable provenance read back | Live migration tests skipped, including both snapshot parameters of durable readback. PostgreSQL 17 and 18 UNVERIFIED. |
| Fresh install, unique IDs/head, downgrade/refusal/reapplication; older shipped histories including quota-door | Static chain/identity checks pass; all live chain legs skipped. Both PostgreSQL majors and complete older-history compatibility audit UNVERIFIED. |

## Handoff

Only this evidence file changes. No tests were added or changed, so there is no
suite inventory delta and no new inventory note is necessary. No code, gates,
ledgers, grants or migration identities were modified.

Next owner actions: resolve the lifecycle authorization through the governed
already-landed policy path outside this lane; restore a usable PostgreSQL test
environment; execute the skipped PG17/PG18 acceptance and migration legs and
obtain genuine specialized CI producer results. Do not count this handoff as
integration approval or issue closure.

Progress: checked 1 assigned issue; done 0 repairs; skipped 0 issues; blocked 1.
