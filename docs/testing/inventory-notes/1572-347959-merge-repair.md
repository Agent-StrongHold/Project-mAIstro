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
## Merged-head checkpoint

Merge completed locally as `5762c6cb6f48` (no push). Inherited develop changes
were preserved; this repair's own edits are the migration conformance test and
this inventory/evidence note. `git diff --cached --check` before committing
reported an inherited blank line at EOF in `docs/issue-42-ci-repair.md:144`;
that unrelated file was not cosmetically rewritten. Working-tree status after
the merge commit was clean.

Executed on that commit with the **resolved assigned base** explicitly supplied
as `RATCHET_BASE_REV=34795962548a33f6b6f7e1234dcea201a9df96ef`:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed, **1326 reviewed identities = 1326 findings**, zero unclassified.
- `uv run python scripts/check-execution-lifecycles.py`: **FAILED**, 19 trusted
  classifications versus 20 discoveries; `maistro.goals.model::GoalStatus`
  still lacks an already-landed authorization. The initial default local base
  was `bbc35234556c`; the explicit current-base run confirms the same blocker.
- `uv run python scripts/check-m1-convergence-freeze.py --base 34795962548a33f6b6f7e1234dcea201a9df96ef`:
  passed, no unapproved new architecture island.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, **15545** unique test identities, no copied-file duplicate evidence.
- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q`:
  **1883 passed, 334 skipped, 6 warnings** in 93.81 seconds. The warnings are
  aiosqlite callbacks against closed loops in adjacent Run tests, not hidden or
  represented as clean teardown.
- Quality diff against the assigned base: only the pre-existing 39-line Goal
  retention additions and 4-line GoalStatus classification; the vulture ledger
  equals the assigned base. This repair adds no grants or classifications.

The actual `integration-scope` producer failure is **UNRESOLVED**. Its local
unit tests pass. Running `ci_merge_group_scope.py --json` over the exact
base-to-candidate changed paths and `check-integration-scope.py --event-name
pull_request --scope-json ... --required-json` succeeds in computing the required
set: docker-build, durable-events, hive-conductor-e2e, hive-conductor-e2e-ui,
object storage (MinIO), postgres (pg17), postgres (pg18), strike-ladder,
wheel-imports. None of those exact-candidate remote successes is established
by local scope calculation. In particular, this version of integration-scope
does **not** aggregate execution-lifecycles, so its reported failure is not
explained merely by the independently reproduced lifecycle gate failure.
No CI policy was changed and no remote check results were fabricated.

Outcome: **BLOCKED**. The merge conflict is repaired and locally committed,
but the trusted-base lifecycle authorization and live PostgreSQL/deployed
composition acceptance cannot be established in this lane. Next: land the
separate GoalStatus policy authorization through the owning process, provide
PG17/PG18 and exact-candidate specialized CI evidence, then revalidate the
explicitly unverified criteria above. No GitHub mutations performed.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0;
errors 1 reproduced policy blocker. Partial merge repair is committed.

## Independent repair revalidation at c0b935fda (job 2ddc1e7a)

Frozen assignment: issue #1572 only, branch `auto-1572`, starting HEAD
`c0b935fda29a2de70d6d0afa6d12246ac46412e7`, trusted/supplied base
`34795962548a33f6b6f7e1234dcea201a9df96ef`. The worktree started clean;
there was no unresolved merge or uncommitted work to salvage. This section is
newly executed evidence, not adoption of the earlier checkpoint's results.
Read repository instructions, the captured issue's complete acceptance criteria,
this job's five driver logs, the supplied prior result, and accepted
ADR-081226-9944, ADR-081226-a66b, ADR-087, ADR-082426-2192 and
ADR-092326-97c4. No architecture exception is proposed.

### Commands and results

All validation used long timeouts in the assigned worktree. Detailed logs are
in `/home/dev/maistro/jobs/2ddc1e7abbd947b4acc9a7cf391b14fc/repair-*.log`.

| Executed command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1326 findings / 1326 reviewed identities, zero unclassified or forbidden. No ledger repair is justified. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL: trusted base 34795962548a has 19 classifications versus 20 discoveries; GoalStatus lacks already-landed authorization. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` | 55 passed, 16 skipped. |
| `uv run pytest packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/test_container_chat_runs.py -x -q` | 1876 passed, 318 skipped, 5 aiosqlite closed-event-loop thread warnings. |
| `uv run pytest tests/migrations -x -q` | 38 passed, 125 skipped. |
| `uv run pytest tests/test_check_execution_lifecycles.py tests/test_check_integration_scope.py -q` | 52 passed, 1 failed: `tests/test_check_execution_lifecycles.py:374` reproduces the unauthorized GoalStatus. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3180 files. |
| `uv run python scripts/check-m1-convergence-freeze.py --base 34795962548a33f6b6f7e1234dcea201a9df96ef` | PASS: no unapproved architecture island. |
| `uv run alembic heads` | PASS: single head 061. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 15545 unique identities, zero duplicate evidence. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL: cannot connect to the Docker daemon. |

### Acceptance checked against current source and tests

Goal test references below are relative to `packages/maistro-core/tests/goals/`.

| Criterion | Current evidence and limits |
| --- | --- |
| Three-backend Goal/GoalRevision round-trip | Shared conformance `test_goal_store_conformance.py:171` passes memory/SQLite; PostgreSQL UNVERIFIED (skipped). |
| Append-only revisions, stale refusal, concurrent single winner, terminal finality | Conformance at lines 197, 229, 278 passes memory/SQLite; races use one store object. PostgreSQL and independent durable-writer races UNVERIFIED. |
| Subgoal parent/Project lineage and recorded Agent ownership changes | Conformance at lines 294, 333 passes memory/SQLite. PostgreSQL UNVERIFIED. |
| Immutable Run admission binding and no implicit Goal outcome | `test_run_goal_binding.py:102,115` exercises real `admit_direct_work` and terminal Run transitions; outcome test passes. Goal advancement after admission and PostgreSQL UNVERIFIED: existing binding tests do not advance the bound Goal revision. |
| Two-principal/two-Workspace isolation; foreign equals missing | Conformance authorization tests pass through `ScopedGoalStore`, which uses `WorkspaceAuthorizer` in production (`goals/authorization.py:52,154`). PostgreSQL UNVERIFIED. |
| Production store composition and shipped Container exposure | `test_goal_wiring.py:43,158` passes real factory/seam tests. Inspected callers: server `main.py:344`, Hive `backend/adapters/maistro_core.py:195`; factory selects store at `container.py:2362`. Both deployed process compositions/restarts UNVERIFIED. Missing/partial PG schemas correctly refuse startup (`goals/wiring.py:61-65`); no old fallback defect is assumed. |
| Restart same Goal/revisions and bound Run | `test_goal_restart_readback.py:36` passes SQLite connection close/reopen, not deployed process restart or Goal advancement after admission. PostgreSQL/deployed-process legs UNVERIFIED. |
| No competing GoalRun/OrchestratorRun/executor/lifecycle authority | Convergence-freeze passes against the resolved supplied base. Separate execution-lifecycle policy gate fails as recorded above. |
| Preserve merged 056/057 identities/ancestry; append unused coordinated Goal revision | Static graph and historical byte-identity tests in `tests/migrations/test_goal_installed_base_upgrade.py:389,416` pass; head 061 follows 060. Central allocation/reservation UNVERIFIED. |
| Actual populated c560d4c/4675101 installed-base forward upgrades without reset/restamp | Existing live tests skipped; PG17 and PG18 UNVERIFIED. |
| Each upgraded base retains facts/statement keys/Run data/planner artifacts and serves reopened Goal/bound Run data | Live tests skipped; PG17 and PG18 UNVERIFIED. Existing durable-composition fixture starts from the planner snapshot only, not both historical bases. |
| Fresh install, single head/unique IDs, downgrade/refusal/reapplication, earlier quota-door history audit | Offline migration checks and single-head command pass. Live PG17/PG18 and complete earlier-history compatibility audit UNVERIFIED. |

### Handoff: BLOCKED, not an implementation repair

The requested vulture scan is already green. No speculative retained identities
were banked and no implementation, tests, grants or gates were changed. This
report is the only changed file; inventory delta remains zero.

`load_authorizations` at `scripts/ratchet_provenance.py:478` reads the trusted
base. A local candidate grant cannot authorize GoalStatus and is outside this
lane's permissions. The owner must establish that authorization independently;
do not disguise the legitimate Goal domain lifecycle to evade the scanner.

The reported **integration-scope failure remains UNRESOLVED**.
`scripts/check-integration-scope.py:20-27` aggregates specialized service checks,
not lifecycle/vulture. Inspection of the supplied dispatch snapshot found no
check-run record with this exact starting HEAD (`repair-captured-check-evidence.json`).
Its unit tests pass, but neither that nor a local scope calculation proves the
actual specialized producers succeeded. No remote lists were refreshed and no
fabricated `--result` values were supplied.

Next: provide the exact-candidate failed integration producer log, independently
land the lifecycle authorization through the owning process, and provide working
PG17/PG18 infrastructure. Re-dispatching only vulture repair cannot resolve these
external prerequisites. No GitHub mutations or issue closure actions occurred.
Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0;
errors 1 reproduced policy blocker, plus unavailable PostgreSQL infrastructure.
