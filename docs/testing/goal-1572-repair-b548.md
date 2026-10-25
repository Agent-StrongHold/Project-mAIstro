# Goal #1572 repair — b5487210

## Frozen scope

- Assigned issue: #1572 only; writer repair, branch `auto-1572`.
- Starting HEAD: `30a55163d64a3b2824cb2e165c8937b01e35adcd`.
- Supplied develop base: `af799688335f9a7dba7999a05e0e13f102c6c5ae`.
- Clean starting worktree; no incoming uncommitted changes to salvage.
- Inputs: supplied dispatch-context.json issue/PR evidence and check-0.log through check-4.log in job b548721011244f6fb7a3067262626397. No GitHub mutations or re-enumeration.
- Repair scope: reproduce integration-scope/execution-lifecycles and exact vulture gate; change only evidence-supported Goal code/tests or reviewed vulture identities, plus this validation report and any required inventory note. No other ledger/grant changes.
- Validation scope: existing Goal tests, production wiring, migration upgrade tests, relevant ADRs and CI gates. Exact relevant file paths will be taken from the supplied branch diff and existing imports, not additional issues/PRs.

## Initial evidence

- Local HEAD matches dispatch; `git status --short` was empty.
- Driver logs: dependency sync passed; ruff check passed; format check passed; targeted tests 55 passed / 16 skipped; core suite inventory 15448 matched. These are supplied evidence, not independently reproduced acceptance.
- The branch differs substantially from supplied develop, including unrelated deleted tests. Preserve existing work; do not reconstruct or discard it. Integration ancestry and external authorization may remain blockers.
- Assumption: this is the assigned writer round (not read-only verifier), as explicitly stated by lane assignment. No develop merge requested unless an actual sync conflict is found.

## Executed validation

- CI-exact vulture scan PASS: 1,328 findings match 1,328 reviewed identities, zero unclassified. No evidence supports a ledger edit.
- `uv run python scripts/check-execution-lifecycles.py` FAIL: GoalStatus lacks already-landed authorization at actual merge base `bbc35234556c8802dd617daf23d9029cc2851045` (19 -> 20 lifecycles). This reproduces the prior policy blocker independently.
- Docker probe at the prescribed socket FAIL: daemon unavailable. Live PG17/PG18 acceptance is not executable using the supplied Docker service.
- Inspection typo: `.github/workflows/integration.yml` not found; skipped. No command executed against an unresolved Git ref. Integration producer invocation will be read from the existing workflow files.
- No GoalStatus authorization match in the supplied develop base either (executed `git show <base>:quality/ratchet-authorizations.json | grep -n GoalStatus`, exit 1). A candidate ledger edit cannot repair the trusted-base requirement.
- Focused core execution PASS: 1,916 passed, 328 skipped, 6 warnings (aiosqlite callbacks on closed event loops); output `/tmp/1572-b548-core.log`.
- Lifecycle gate regression FAIL: `tests/test_check_execution_lifecycles.py:374`, 28 passed / 1 failed, independently reproducing missing GoalStatus authorization.
- Migration suite: 38 passed / 125 skipped. Live database claims remain UNVERIFIED.
- Ruff lint and formatting PASS (3,170 files); convergence freeze PASS against supplied develop base; Alembic reports one head, `061`.

## Architecture / evidence boundary

Read accepted ADR-081226-9944, ADR-081226-a66b, ADR-087, ADR-082426-2192 and ADR-092326-97c4. Preserve canonical ownership, execution spine, additive schema evolution and shared durable authority. No conflicting requirement needs reconciliation.

`goals/wiring.py:61-65` refuses incomplete PostgreSQL schema, rather than selecting memory or SQLite. `goals/authorization.py:144-162` uses the canonical Workspace authorizer and returns the same refusal for missing/foreign Goals. The existing tests exercise these real seams. No replacement authority or speculative production repair is warranted.

`scripts/check-integration-scope.py:20-27` aggregates specialized integration producers (PostgreSQL, object storage, durable events, strike ladder, Hive E2E, wheel imports and Docker build), not the lifecycle or vulture gates. Its aggregate failure alone does not identify a defective Goal implementation. Do not feed invented success results to make it pass.

The actual workflow `.github/workflows/integration-scope.yml:129-150` waits for required producer results and fails on unsuccessful or missing evidence. Inspection of supplied `sources[].data.check_runs` found **zero exact-starting-head check runs**. The exact producer failure is therefore UNRESOLVED from this snapshot; no remote refresh was performed. `scripts/ratchet_provenance.py:478-504` explicitly requires already-landed authorization; this round cannot manufacture it.

Both shipped callers reach the shared factory: Hive `backend/adapters/maistro_core.py:195`, server `maistro_server/main.py:344`. The factory selects Goals at `container.py:2362`, exposes them at line 2648, and wraps its own Workspace store at lines 274-284. Executed factory tests do not establish deployed durable process restart.

## Commands and outcomes

All validation commands used 1,200-second tool timeouts. Inspection commands used 60-second timeouts.

| Command | First-hand result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,328 matching identities, zero unclassified. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL, missing trusted-base GoalStatus authorization. CI-exact invocation: quality.yml:1501. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL, daemon unavailable. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py packages/maistro-core/tests/test_container_chat_runs.py -x -q` | 1,916 passed, 328 skipped, 6 warnings; `/tmp/1572-b548-core.log`. |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed at line 374. |
| `uv run pytest tests/migrations -x -q` | 38 passed, 125 skipped. |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py::TestTheMergedIdentities -q` | 2 passed, including historical-byte equality (not skipped). |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS, 3,170 files. |
| `uv run python scripts/check-m1-convergence-freeze.py --base af799688335f9a7dba7999a05e0e13f102c6c5ae` | PASS. |
| `uv run alembic heads` | PASS, single head 061. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 15,448 unique identities, no duplicate evidence. |
| `git diff --check` | PASS. |

## Criterion-to-evidence map

Goal test paths below are under `packages/maistro-core/tests/goals/`. Passed evidence is limited to what was actually executed above, not earlier reports or comments.

| Acceptance criterion | Executed evidence and remaining limits |
| --- | --- |
| Goal/GoalRevision round-trip on all three backends | `test_goal_store_conformance.py:171` passes memory/SQLite, asserting stored desired state, conditions, author and revision. PostgreSQL skipped: UNVERIFIED. |
| Append-only, stale-revision refusal, exactly one concurrent winner | Conformance lines 197, 229, 278 pass memory/SQLite; prior revision retained, stale write refused, concurrent append/terminal-transition one-winner checks. Tests race one store instance; independent-writer and PostgreSQL behavior UNVERIFIED. |
| Subgoal parent/Project preservation and explicit recorded Agent change | Conformance lines 294, 333 pass memory/SQLite, including invalid scope refusal and both old/new Agent in history. PostgreSQL UNVERIFIED. |
| Run admission binding immutable after admission | `test_run_goal_binding.py:102,115` passes memory/SQLite persistence and terminal transitions; half-binding refused, Run outcome does not move Goal state. Advancing the Goal revision after admission is not exercised by these tests: UNVERIFIED, as is PostgreSQL. |
| Two principals/two Workspaces isolated; foreign equals missing | Conformance lines 398, 472 pass memory/SQLite via ScopedGoalStore and canonical WorkspaceAuthorizer; refusal type/message compared, unauthorized mutation leaves history unchanged. PostgreSQL UNVERIFIED. |
| Production composition wires the store and shipped Container exposes it | `test_goal_wiring.py:43,158` passes actual shared factory exposure and authorized read/write seam; both production call sites confirmed above. Deployed Hive/server durable startup/restart UNVERIFIED. |
| Durable reopen of same Goal/revisions/bound Run | `test_goal_restart_readback.py:36` passes SQLite connection close/reopen. This is not a process restart of Hive/server; deployed compositions and PostgreSQL UNVERIFIED. |
| No competing GoalRun/OrchestratorRun/executor/product-private Goal lifecycle | Convergence freeze PASS against supplied base. Separate execution-lifecycle policy gate FAIL; no bypass. |
| Preserve merged user-model 056/planner 057 identity and ancestry; append unused coordinated identity | `tests/migrations/test_goal_installed_base_upgrade.py:389,416`: graph and historical bytes PASS; Goal 061 follows 060. Central allocation coordination UNVERIFIED. |
| Populated actual c560d4c/4675101 snapshots forward-upgrade normally | Live fixtures skipped; both PG17 and PG18 UNVERIFIED. |
| After each upgrade: three Goal tables usable, user facts/keys/Run rows preserved, planner artifacts/head retained, reopen Goal/Run provenance | Both PG17 and PG18 UNVERIFIED. Existing durable-reopen test covers only planner snapshot, not both installed-base snapshots. |
| Fresh install, single head/unique IDs, supported downgrade/refusal/reapplication, quota ancestry and earlier shipped-history audit | Static migration tests and single-head command PASS. Both live PostgreSQL major legs, complete older-history compatibility audit and allocation coordination UNVERIFIED. |

## Handoff

Only `docs/testing/goal-1572-repair-b548.md` changed in this round. No new tests, so no inventory delta. No source, workflow, ledger or grant edits. The explicit vulture-ledger repair permission does not justify changing an already matching ledger.

The previous block is **not resolved**: an independently landed GoalStatus authorization is required before this implementation can pass the lifecycle gate. The integration-scope producer failure also needs exact-candidate evidence. Docker/PG17/PG18 infrastructure is required to prove durable acceptance. These are concrete blockers, not a request to weaken gates or waive acceptance.

Progress: checked 1 assigned item; done 0 repairs; skipped 0 items; errors 2 blocker categories (lifecycle gate failure, database infrastructure unavailable). Next: obtain trusted-base authorization through the separate owner process, supply the failed integration producer log, then execute live PostgreSQL acceptance. Commit this report locally; no push, GitHub mutation, closure or integration approval. Verdict: **BLOCKED**.
