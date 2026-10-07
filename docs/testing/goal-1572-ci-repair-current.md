# Issue #1572 focused CI repair

## Frozen scope

- Assigned issue: #1572 only; branch `auto-1572`.
- Starting HEAD: `39a58c2429438c7d5d86631121383057b7f35d0d` (clean).
- Dispatch base: `28614700bd9ab0223eac06924a204af4a5cc25d9`.
- Input snapshot: job `b66e1028a8124c6eb37ab59616ef479c` dispatch-context.json and check-0.log through check-4.log. No GitHub refresh or mutation.
- Repair targets: evidence-confirmed vulture retained identities in `quality/vulture-baseline.json`; genuinely dead Goal code only if demonstrated; this report. Existing Goal/run implementation, adjacent tests, migrations, ADRs and CI configuration are read/validation scope, not permission to repair unrelated code.
- Ambiguity: integration-scope failure does not identify its underlying gate. Proceed by inspecting supplied logs and executing the explicitly requested gates. Earlier verification claims are not treated as executed evidence.
- Existing implementation and unrelated merged changes are preserved. No uncommitted salvage was needed.

## Results

First-hand requested vulture scan PASS: 1,328 reviewed identities / 1,328 findings; zero unclassified/forbidden. No ledger repair is justified. First-hand execution-lifecycles gate FAIL: `maistro.goals.model::GoalStatus` lacks already-landed authorization (trusted base `9bd1a93eefc4`, 19 -> 20 lifecycles). Docker probe FAIL: cannot connect to `unix:///var/run/docker.sock`; PostgreSQL validation is currently unavailable. These are current results, not inherited claims.

Executed focused core tests: 1,822 passed / 311 skipped, six adjacent aiosqlite closed-event-loop warnings. Lifecycle gate regression suite: 28 passed / 1 failed at `tests/test_check_execution_lifecycles.py:374`, reproducing the authorization failure. Migration suite: 38 passed / 125 skipped. Ruff lint and format PASS (3,145 files). Convergence freeze against the dispatch base PASS. Alembic has single head `061`.

Read accepted ADR-081226-9944, ADR-081226-a66b, ADR-087, ADR-082426-2192, and ADR-092326-97c4. No architecture reconciliation or alternate authority is proposed. Current production `goals/wiring.py:61-65` already fails closed on an unmigrated PostgreSQL pool; the older report's fallback finding is no longer current. Existing tests exercise absent/partial schemas with and without SQLite available. No speculative rewrite is warranted.

## Command record

All commands below were executed in the assigned worktree in this pass, with long validation timeouts:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,328 findings, matching reviewed identities. CI arguments confirmed at `.github/workflows/quality.yml:1039`. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL, missing GoalStatus authorization. CI command confirmed at `.github/workflows/quality.yml:1501`. |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed at line 374, same authorization failure. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` | 1,822 passed, 311 skipped, six adjacent SQLite thread warnings. |
| `uv run pytest packages/maistro-core/tests/test_container_chat_runs.py -x -q` | 42 passed. |
| `uv run pytest tests/migrations -x -q` | 38 passed, 125 skipped. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS, 3,145 files. |
| `uv run python scripts/check-m1-convergence-freeze.py --base 28614700bd9ab0223eac06924a204af4a5cc25d9` | PASS. |
| `uv run alembic heads` | PASS, single head `061`. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 14,970 unique identities, zero duplicated evidence. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL, daemon unavailable. |

Driver logs were also inspected: dependency sync, lint and formatting succeed; focused tests report 55 passed / 16 skipped; inventory reports 14,970. These are distinguished from this pass's independently executed commands above.

## Acceptance map

Source review covered the Goal models, durable mutation paths, Workspace-authorized seam, backend selection, Run admission/storage binding, adjacent conformance/wiring/restart tests, and migration upgrade fixtures. Test references below are under `packages/maistro-core/tests/goals/` unless specified.

| Criterion | Current executed evidence / limits |
| --- | --- |
| Goal and GoalRevision round-trip on all three backends | `test_goal_store_conformance.py:171` passes memory/SQLite. PostgreSQL UNVERIFIED (skipped). |
| Append-only revisions, stale refusal, concurrent single winner; terminal finality | Conformance tests at lines 197, 229 and 278 pass memory/SQLite. Independent durable writers and PostgreSQL UNVERIFIED; concurrency tests use one store instance. |
| Subgoal parent/Project lineage and recorded owning-Agent transition | Conformance tests at lines 294 and 333 pass memory/SQLite. PostgreSQL UNVERIFIED. |
| Admission binds immutable historical Goal provenance; no implicit Goal outcome | `test_run_goal_binding.py:102,115` and outcome test pass memory/SQLite. Tests do not advance the Goal revision after admission; that scenario and PostgreSQL UNVERIFIED. |
| Two principals/two Workspaces isolated; foreign indistinguishable from missing | Conformance tests at lines 398 and 472 pass memory/SQLite through `ScopedGoalStore` and canonical `WorkspaceAuthorizer`. PostgreSQL UNVERIFIED. |
| Production composition and shipped Container exposure | `test_goal_wiring.py:43,158` exercises the real shared factory and seam. Source callers: server `main.py:344`, Hive `backend/adapters/maistro_core.py:194`; factory selects Goals at `container.py:2378`. Missing/partial PG schema refusal tests pass. Both deployed durable process compositions UNVERIFIED. |
| Restart supported durable composition; same Goal/revisions and bound Run | `test_goal_restart_readback.py:36` passes SQLite close/reopen. This is store connections, not a deployed Container/process restart; deployed processes and PostgreSQL UNVERIFIED. |
| No GoalRun/OrchestratorRun, second executor or product-private lifecycle | Convergence-freeze passes against dispatch base; distinct execution-lifecycle policy gate fails as above. |
| Preserve merged 056/057 meaning/ancestry; append coordinated unused identity | Static graph and byte-identical historical snapshot checks in `tests/migrations/test_goal_installed_base_upgrade.py:389,416` pass. Head 061 follows 060. Central allocation/reservation UNVERIFIED. |
| Actual populated c560d4c/4675101 forward upgrades without restamping/reset | Live historical upgrade tests skipped; PG17 and PG18 UNVERIFIED. |
| After each upgrade: three Goal tables, preserved user facts/keys/Run data, planner artifacts, target head, reopened Goal/bound provenance | Live tests skipped; PG17 and PG18 UNVERIFIED. |
| Fresh install, unique IDs/single head, supported downgrade/refusal, reapplication and earlier quota ancestry audit | Static migration checks and single-head command pass. Live PG17/18 and complete earlier-history compatibility audit UNVERIFIED. |

## Blocker and handoff

`load_authorizations` at `scripts/ratchet_provenance.py:478` reads grants from the trusted base. A local candidate grant cannot authorize itself. The gate selects base `9bd1a93eefc4`; inspection of the separately supplied develop SHA also found no GoalStatus grant. This lane may repair vulture debt, not change lifecycle grants, weaken gates, or disguise the real Goal domain lifecycle. An independently landed authorization is an external prerequisite.

The reported **integration-scope failure remains UNRESOLVED**. `scripts/check-integration-scope.py:20-27` aggregates PostgreSQL, object storage, events, strike-ladder, Hive E2E, wheels and Docker; it does not aggregate execution-lifecycles or vulture. Inspection of captured dispatch check-runs supplies no exact-starting-head failing producer evidence. Earlier-head failures are not attribution for this candidate. No fabricated `--result` inputs or aggregate success claims were used. Next dispatch needs the actual failed specialized producer's exact-SHA log.

Changed file: only this report. No implementation, tests, ledgers, grants, CI gates or inventory counts changed; no new inventory-delta note is required. Existing repairs were preserved. Current outcome is **BLOCKED**, not integration approval. No remote mutations, speculative merge, or issue closure actions were performed.

Progress: checked 1 assigned item; done 0 repairs; skipped 0 items; errors 1 reproduced policy blocker, plus unavailable PostgreSQL infrastructure. Next: independently land the GoalStatus authorization, supply the failing integration producer log, and make PG17/18 available before attempting the remaining acceptance legs. `git diff --check` passed before the local checkpoint commit; the worktree was clean afterward. Do not repeat a speculative vulture amendment when its exact scan is green.
