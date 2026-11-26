# Issue #1572 repair checkpoint (c6d584)

## Frozen scope

- Assigned issue: #1572 only; branch `auto-1572`.
- Starting HEAD: `fa9166617177d031fcc4f0c126d7fbcdefd3debb`.
- Supplied develop base: `af799688335f9a7dba7999a05e0e13f102c6c5ae`.
- Starting worktree clean; no incoming edits to salvage.
- Process the existing Goal implementation and the specifically assigned integration-scope / exact-debt-ledger repair. No remote mutations, grants, or unrelated implementation.
- Candidate edit scope: `quality/vulture-baseline.json` (explicit repair exception), genuinely dead code identified by that scan, this evidence note, and focused Goal tests/inventory notes only if a real regression requires them. Existing implementation diff is the inspection scope; do not enumerate further issues or PRs.

## Initial evidence and assumptions

Read the supplied dispatch snapshot's complete issue body, including installed-base migration acceptance. Driver logs check-0 through check-4 report dependency resolution, passing lint/format, 55 tests passed with 16 skipped, and matching core suite inventory. These do not establish PostgreSQL or installed-base acceptance.

Assumption: this is the writer lane (explicit assigned repair), not the read-only verifier lane. Prior lifecycle authorization findings must be rerun against the supplied current base; no grant edits are authorized here. Exact-debt-ledger amendments are permitted only for reviewed retained identities reported by the requested scan.

## Results

First-hand exact vulture scan PASS: 1,328 findings match 1,328 reviewed identities, no unclassified findings. No vulture ledger change is justified. Its trusted base is now `bbc35234556c`, not the older base in prior findings.

First-hand `uv run python scripts/check-execution-lifecycles.py` FAIL: 19 classified -> 20 discovered, `maistro.goals.model::GoalStatus` has no already-landed authorization in trusted base `bbc35234556c`. The prior blocker persists after the develop sync. Do not conceal this domain state or edit unauthorized lifecycle grants/ledgers.

`DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` FAIL: cannot connect to daemon. Live PostgreSQL acceptance cannot be claimed. `scripts/check-integration-scope.py:20-27` aggregates specialized integration producers, not vulture/lifecycle. Missing producer logs cannot be repaired by guessing scanner findings or fabricating success arguments.

Read accepted ADR-087 (additive schema evolution), ADR-092326-97c4 (shared PostgreSQL Workspace authority/fail-closed), ADR-082426-2192 (one production Container/spine). Goal wiring respects selected backend and refuses missing PostgreSQL schema. No architecture exception or new authority is proposed. The issue remains blocked.

Focused core validation completed: 1,916 passed, 328 skipped, six aiosqlite closed-event-loop thread warnings (output `/tmp/1572-c6d584-core.log`). Migration tests: 38 passed, 125 skipped. Lifecycle gate regression: 28 passed, one failed at `tests/test_check_execution_lifecycles.py:374`, reproducing the missing authorization against `bbc35234556c`. Ruff lint and format PASS (3,170 files); Alembic reports single head 061; convergence freeze PASS against supplied base `af799688335f9a7dba7999a05e0e13f102c6c5ae`.

Source inspection confirms both production callers use the shared factory: server `main.py:344` and Hive `backend/adapters/maistro_core.py:195`. Container `container.py:2362,2648` composes the selected Goal store; lines 274-284 derive the principal-carrying seam using the Container's Workspace store. The executed exposure/end-to-end tests use the shipped factory, but do not deploy/restart either product.

Core suite inventory PASS: 15,448 unique identities, no duplicated evidence. `git diff --check` PASS. This round changes only this evidence note, adds no tests, and changes no inventory counts, so no inventory-delta amendment is needed.

## Commands and outcomes

All Python commands used the assigned worktree's `uv run`; long-running commands had 1,200-second timeouts.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,328 reviewed findings, zero unclassified. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL; missing trusted-base GoalStatus authorization. CI invocation confirmed at `.github/workflows/quality.yml:1501`. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL; daemon unavailable. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py packages/maistro-core/tests/test_container_chat_runs.py -x -q` | 1,916 passed / 328 skipped / 6 warnings. |
| `uv run pytest tests/migrations -x -q` | 38 passed / 125 skipped. |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed / 1 failed at line 374. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS; 3,170 files. |
| `uv run alembic heads` | PASS; single head 061. |
| `uv run python scripts/check-m1-convergence-freeze.py --base af799688335f9a7dba7999a05e0e13f102c6c5ae` | PASS. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS; 15,448 unique identities. |
| `git diff --check` | PASS. |

## Criterion-to-evidence map

Paths in the first seven rows are relative to `packages/maistro-core/tests/goals/`. Passed tests are from the first-hand focused run above; skipped legs are not evidence of acceptance.

| Issue criterion | Evidence and limits |
| --- | --- |
| Goal/GoalRevision round-trip on three backends | `test_goal_store_conformance.py:171` passes memory and SQLite. PostgreSQL UNVERIFIED. |
| Append-only revisions, stale refusal, concurrent single winner, terminal finality | Conformance lines 197, 229, 278 passes memory/SQLite; races use one store instance. PostgreSQL and independent durable writers UNVERIFIED. |
| Subgoal parent/Project and recorded Agent reassignment | Conformance lines 294, 333 passes memory/SQLite. PostgreSQL UNVERIFIED. |
| Run admission binds immutable historical Goal revision | `test_run_goal_binding.py:102,115` passes memory/SQLite, including persisted binding and terminal Run transitions. Outcome independence test passes. These tests do not advance the Goal revision after admission; that scenario and PostgreSQL UNVERIFIED. |
| Cross-Workspace isolation; foreign equals missing | Conformance lines 398, 472 passes memory/SQLite through `ScopedGoalStore` and real Workspace authorization, comparing refusal type/message. PostgreSQL UNVERIFIED. |
| Both production compositions expose store | `test_goal_wiring.py:43,171` passes shipped shared factory and authorized seam. Actual Hive/server callers confirmed above. Live durable product startup/restart UNVERIFIED. |
| Durable restart retains Goals/revisions/bound Run | `test_goal_restart_readback.py:36` passes SQLite connection close/reopen. It does not restart a deployed product; live PostgreSQL and deployed Container restart UNVERIFIED. |
| No competing GoalRun/OrchestratorRun/executor/private lifecycle | Convergence freeze PASS against supplied base. Separate lifecycle-policy gate FAIL remains a blocking prerequisite. |
| Preserve user-model 056/planner 057 meanings and ancestry; append new Goal identity | Installed-base suite checks graph and historical bytes (`tests/migrations/test_goal_installed_base_upgrade.py:389,416`); static migration checks execute, live upgrades skip. Head is 061, parent 060. Central allocation coordination UNVERIFIED. |
| Populated actual c560d4c/4675101 snapshot forward upgrades without resetting/restamping | Both live PostgreSQL major legs UNVERIFIED; Docker unavailable and migration tests skipped. |
| After upgrade: three tables, retained facts/statement keys/Run rows, planner artifacts, head, reopened Goal/Run provenance | Both PostgreSQL majors UNVERIFIED; live tests skipped. |
| Fresh install, unique IDs/single head, downgrade/refusal/reapplication, older quota ancestry audit | Static graph/head checks PASS. Live PostgreSQL 17/18 install/upgrade/downgrade/reapplication and complete older supported history audit UNVERIFIED. |

## Handoff

No evidence supports a vulture repair at this head; editing the already-matching ledger would be cosmetic or harmful. No source, test, ledger, grant, workflow, or migration changes were made in this round. The only authored file is this report.

The lifecycle prerequisite must be independently authorized on the trusted base before this branch can pass its gate; this lane cannot grant it. The supplied `integration-scope: failure` does not identify its failed producer. Its aggregate consumes PostgreSQL, object storage, durable events, strike ladder, Hive E2E, wheel imports, and Docker build results; do not mislabel a vulture pass as an integration-scope repair. Producer-specific failure evidence and working PostgreSQL 17/18 infrastructure are required for the remaining acceptance. No synthetic `--result ...=success` values were passed to that gate.

Progress: checked 1 assigned item; done 0 repairs (no authorized evidence-backed repair available); skipped 0 items; errors 2 (lifecycle policy failure and unavailable Docker); next: independently landed lifecycle authorization, actual failing integration producer log, and live two-major PostgreSQL validation. Overall verdict **BLOCKED**. Commit this evidence locally; no push, GitHub mutation, issue closure, or integration approval.
