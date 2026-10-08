# Goal #1572 repair — job 9414

## Frozen scope

- Issue: #1572 only; assigned worktree `/home/dev/Git/wt/auto-1572`, branch `auto-1572`.
- Starting HEAD: `71c00a188e1447ac329d3cd82784527372fc0544`; supplied develop base: `af799688335f9a7dba7999a05e0e13f102c6c5ae`.
- Initial worktree clean. Preserve all existing implementation commits.
- Repair targets: reproduced integration-scope failures, specifically execution-lifecycle provenance and the explicitly authorized vulture per-identity ledger repair. Review files are the existing branch diff, adjacent Goal/Run tests, referenced ADRs, gate implementations and CI invocations. No unrelated issues or linked PR work.
- Supplied logs inspected: dependency sync, Ruff check/format, Goal tests (55 passed, 16 skipped), core suite inventory passed. These are driver evidence, not proof of skipped durable acceptance legs.
- Assumption: writer lane; no conflict reported locally, so no develop merge unless evidence requires it. No remote mutations, authorization/grant changes, or gate weakening.

## Results

First-hand CI-exact vulture scan PASS: 1,328 reviewed identities match 1,328 findings, zero unclassified. No ledger amendment is justified. First-hand execution-lifecycles gate FAIL: `maistro.goals.model::GoalStatus` lacks already-landed authorization in trusted base `bbc35234556c` (19 -> 20 lifecycles). Docker probe FAIL: cannot connect to `unix:///var/run/docker.sock`. These reproduce the prior blockers at the exact assigned starting head rather than assuming old findings remain true.

`scripts/check-integration-scope.py:20-27` aggregates specialized integration producers, not vulture or execution-lifecycles. The supplied aggregate failure is not enough to identify a repair; no synthetic success results will be supplied. Current Goal wiring explicitly refuses incomplete PostgreSQL schema instead of falling back to a different backend (`goals/wiring.py:61-65`). Preserve that behavior.

Read accepted ADR-081226-9944 (ownership), ADR-081226-a66b (single execution lifecycle), ADR-082426-2192 (shared Container), ADR-092326-97c4 (shared PostgreSQL authority/fail closed), and ADR-087 (additive migration evolution). No conflicting instruction requires reconciliation and no alternate authority is proposed.

First-hand focused core tests: **1,916 passed, 328 skipped, 6 warnings** in 53.61s (`/tmp/1572-9414-core.log`). Warnings are aiosqlite thread callbacks against closed event loops. Lifecycle gate regression: **28 passed, 1 failed** at `tests/test_check_execution_lifecycles.py:374`, reproducing the missing trusted-base GoalStatus grant. Migration tests: **38 passed, 125 skipped**; live PostgreSQL upgrades remain UNVERIFIED.

Ruff lint and format PASS (3,170 files); convergence freeze PASS against supplied develop base; Alembic single head `061`; core inventory PASS (15,448 unique test identities, no duplicate evidence); `git diff --check` PASS. Source confirms both shipped callers use `create_container`: server `main.py:344`, Hive `backend/adapters/maistro_core.py:195`. Container selects Goals at `container.py:2362`, exposes them at line 2648, and derives the authorized seam from its own Workspace store at lines 274-284. Executed factory tests cover this wiring but do not start/restart deployed products.

## Commands executed in this pass

Validation commands used 1,200-second timeouts and the assigned worktree.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,328 matching reviewed identities. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL, missing GoalStatus trusted-base authorization. CI command is `.github/workflows/quality.yml:1501`. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL, daemon unavailable. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py packages/maistro-core/tests/test_container_chat_runs.py -x -q` | 1,916 passed, 328 skipped, 6 warnings. |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed at line 374. |
| `uv run pytest tests/migrations -x -q` | 38 passed, 125 skipped. |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py::TestTheMergedIdentities -q` | 2 passed; graph shape and historical migration bytes. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS, 3,170 files. |
| `uv run python scripts/check-m1-convergence-freeze.py --base af799688335f9a7dba7999a05e0e13f102c6c5ae` | PASS. |
| `uv run alembic heads` | PASS, single head 061. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 15,448 unique identities. |
| `git diff --check` | PASS. |

An executed JSON inspection of captured `sources[].data.check_runs` found **zero check runs at the exact starting HEAD**. No current producer log is available there to attribute the supplied integration-scope failure. This is not a claim that remote CI passed or that older runs contain no failures; no remote refresh was performed.

## Acceptance map

Test paths in the first eight rows are relative to `packages/maistro-core/tests/goals/`; results refer to the first-hand executions above.

| Criterion | Evidence / explicit limits |
| --- | --- |
| Goal and GoalRevision round-trip on three backends | `test_goal_store_conformance.py:171` passes memory/SQLite; PostgreSQL UNVERIFIED (skipped). |
| Append-only revisions, stale refusal and concurrent one-winner updates | Conformance lines 197, 229, 278 pass memory/SQLite. Races use one store instance; independent durable writers and PostgreSQL UNVERIFIED. Terminal finality also passes. |
| Subgoal parent/Project preservation; explicit recorded Agent change | Conformance lines 294, 333 pass memory/SQLite. PostgreSQL UNVERIFIED. |
| Run admission binding and immutable historical revision | `test_run_goal_binding.py:102,115` passes memory/SQLite storage and terminal transitions. The tests do not advance the Goal revision after admission: that scenario and PostgreSQL UNVERIFIED. Outcome independence test passes. |
| Two principals/two Workspaces isolated; foreign equals missing | Conformance lines 398, 472 pass memory/SQLite through `ScopedGoalStore` and canonical `WorkspaceAuthorizer`, comparing refusal type/message. PostgreSQL UNVERIFIED. |
| Production wiring and Container exposure | `test_goal_wiring.py:43,171` passes shared factory exposure/end-to-end authorized seam. Both actual production callers confirmed above; deployed Hive/server durable startup and restart UNVERIFIED. |
| Restart reads same Goal/revisions and bound Run | `test_goal_restart_readback.py:36` passes SQLite store connection close/reopen; this is not a product process restart. PostgreSQL and deployed durable compositions UNVERIFIED. |
| No competing execution authority | Convergence freeze PASS against supplied base. Separate lifecycle-policy gate FAIL, not bypassed. |
| Preserve merged 056/057 meaning and ancestry; append unused coordinated Goal identity | `tests/migrations/test_goal_installed_base_upgrade.py:389,416`: both static checks pass, including bytes from historical commits. Head 061 follows 060. Central allocation coordination UNVERIFIED. |
| Actual populated c560d4c and 4675101 snapshots forward-upgrade without reset/restamping | Live tests skipped; PG17 and PG18 UNVERIFIED. |
| After each upgrade: three Goal tables, retained user facts/keys/Run rows, planner artifacts, intended head, reopened Goal/Run provenance | PG17 and PG18 UNVERIFIED. Existing reopen fixture covers the planner snapshot, not both installed-base snapshots; no claim of complete coverage. |
| Fresh install, unique IDs/single head, supported downgrade/refusal/reapplication, older quota ancestry compatibility | Static migration checks and single-head command PASS. Live PG17/18 paths and complete earlier supported-history audit UNVERIFIED. |

## Handoff / residual blockers

Only this evidence report changed. No new tests or inventory deltas, no source changes, and no ledger/grant/workflow edits. The exact vulture scan is green; amending a matching ledger would not repair the reported failure.

`scripts/ratchet_provenance.py:478` requires authorization from the trusted base, so a candidate grant cannot authorize itself. An independently landed GoalStatus grant remains an external prerequisite. This lane is not authorized to alter it or hide the domain lifecycle from the scanner. Integration-scope additionally needs the exact failing specialized producer's logs, rather than a guessed vulture repair. PostgreSQL acceptance requires available PG17/PG18 infrastructure.

Progress: checked 1 assigned item; done 0 repairs (no authorized evidence-backed repair available); skipped 0 items; errors 2 (reproduced lifecycle-policy failure and unavailable Docker); next: independently land the lifecycle authorization, supply the exact-head integration producer failure log, and execute both PostgreSQL major acceptance legs. Verdict **BLOCKED**. Commit this checkpoint locally; no push, remote mutation, issue closure, or integration approval.
