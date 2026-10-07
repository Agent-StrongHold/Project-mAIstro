# Issue #1572 current CI repair

## Frozen scope

- Assigned issue: #1572 only; branch `auto-1572`.
- Starting HEAD: `cf7e21ed30655599a33719f7d82d2affa682c1db` (verified); worktree initially clean.
- Supplied develop reference: `e1b13dcd15dedd637404c38dfe1900921aba2b8c` (resolved).
- Evidence snapshot: `/home/dev/maistro/jobs/5e1344732b374b9eb9b8a80b8aac0ea6/dispatch-context.json` and check-0.log through check-4.log. No remote enumeration or mutations. Read the previous job's `result.json`, but independently reran the validations below rather than inheriting its verdict.
- Files in repair scope: canonical goals and Run binding implementation/tests already present, relevant CI gate scripts (inspection only), `quality/vulture-baseline.json` (only if exact scan proves reviewed debt), and this report. No other ledger/grant edits permitted.
- Role ambiguity: prompt includes verifier and writer directions; lane explicitly assigns repair, so proceed as writer with focused validation and local commit.

## Initial evidence

Driver logs report dependency sync success, lint success, format success, goal tests 46 passed / 16 skipped, and core inventory success (14,961 identities). These are driver evidence, not independently re-executed acceptance claims.

The supplied develop-to-HEAD diff includes substantial unrelated divergence. This round will not attempt a speculative synchronization or modify those files. The branch already includes prior repair reports; inspect them and reproduce the named gates before changing production code.

## Results

First-hand exact vulture command passes: 1,328 reviewed identities / 1,328 findings, zero unclassified/forbidden. No vulture ledger amendment is justified.

First-hand `uv run python scripts/check-execution-lifecycles.py` fails: `maistro.goals.model::GoalStatus` lacks already-landed authorization (19 classified / 20 discovered). Trusted base selected by the gate is `9bd1a93eefc4`, not the supplied develop tip. This is a policy blocker outside the permitted ledger repair. Do not disguise or delete the legitimate Goal domain lifecycle to evade it.

Read the captured issue body, including its installed-base migration acceptance additions.

Executed focused core validation: `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q`: **1,813 passed, 311 skipped**, six adjacent Run SQLite worker/event-loop warnings (full output in this job's `worker-core.log`). `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` fails: daemon unavailable; PostgreSQL legs remain unverified.

`uv run pytest tests/test_check_execution_lifecycles.py -x -q`: **28 passed, 1 failed** at line 374, reproducing the missing trusted-base GoalStatus authorization.

`uv run pytest tests/migrations -x -q`: **38 passed, 125 skipped**. `uv run python scripts/check-m1-convergence-freeze.py --base e1b13dcd15dedd637404c38dfe1900921aba2b8c`: PASS. `uv run ruff check .` and `uv run ruff format --check .`: PASS (3,145 files formatted).

Source confirms server `main.py:344` and Hive `backend/adapters/maistro_core.py:194` call the shared Container factory; `container.py:2377` selects the Goal store. `scripts/check-integration-scope.py:20-27` aggregates specialized integration jobs, not lifecycle or vulture. Exact failed producer evidence is still needed; no causal attribution or aggregate success is inferred.

`uv run alembic heads`: PASS, single head `061`. `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 14,961 unique identities and zero duplicate evidence. `git diff --check`: PASS. Inspection of the supplied develop ref's authorization file found no GoalStatus grant. No unresolved merge exists, and a speculative develop merge would not supply that missing authorization.

## Architecture and acceptance review

Read accepted ADR-081226-9944 (product ownership), ADR-081226-a66b (Run/NodeRun/Attempt), ADR-087 (schema evolution), ADR-082426-2192 (server Container), and ADR-092326-97c4 (shared PostgreSQL Workspace authority). No alternate scheduler, authorization seam or Goal owner is introduced by this round. Do not reconcile the policy failure by changing GoalStatus into an unscannable representation.

Tests and the production wiring/authorization were inspected, rather than treating test counts as acceptance. All test references below are under `packages/maistro-core/tests/goals/` unless stated otherwise.

| Acceptance criterion | Current executed evidence and limits |
| --- | --- |
| Goal and GoalRevision round-trip on all three backends | `test_goal_store_conformance.py:171` passes memory and SQLite (including content and reopened-store equality). PostgreSQL UNVERIFIED. |
| Append-only revisions, stale refusal, one concurrent winner; final terminal states | Conformance tests at lines 197, 229 and 278 pass memory/SQLite. Concurrency uses one store object; independent durable writers and PostgreSQL UNVERIFIED. |
| Subgoal parent/Project lineage and recorded Agent transition | Conformance tests at lines 294 and 333 pass memory/SQLite. PostgreSQL UNVERIFIED. |
| Run admission binding and immutable historical revision | `test_run_goal_binding.py:102,115` passes memory/SQLite through `admit_direct_work` and terminal transition. Tests do not advance Goal revision after admission, so that historical-provenance scenario and PostgreSQL remain UNVERIFIED. |
| Cross-Workspace isolation; foreign equals missing | Conformance tests at lines 398 and 472 pass memory/SQLite through real `WorkspaceAuthorizer` in `ScopedGoalStore`; PostgreSQL UNVERIFIED. |
| Both production compositions and Container exposure | `test_goal_wiring.py:41,132` passes real in-memory factory/seam tests; server and Hive source callers confirmed above. Both deployed durable process compositions UNVERIFIED. |
| Restart supported durable composition with same Goal/revisions/bound Run | `test_goal_restart_readback.py:36` passes SQLite close/reopen of store connections. It does not restart a deployed Container/process, and does not advance Goal revision after admission. Deployed process and PostgreSQL evidence UNVERIFIED. |
| No competing executor or product-private lifecycle | Convergence freeze passes against supplied develop SHA. Execution-lifecycle policy gate remains blocked on missing authorization. |
| Preserve merged 056/057 meaning/ancestry, append unused coordinated Goal ID | `tests/migrations/test_goal_installed_base_upgrade.py:389,416` static graph/snapshot tests pass; single head 061 follows 060. Central reservation UNVERIFIED. |
| Populated actual c560d4c/4675101 forward upgrades without restamping | Existing installed-base live tests skipped; both PG17 and PG18 UNVERIFIED. |
| Post-upgrade Goal tables, user-model/Run data, planner artifacts, version and reopened bound provenance | Existing installed-base live tests skipped; both PostgreSQL majors UNVERIFIED. |
| Fresh install, unique IDs/single head, downgrade/refusal and reapplication; older quota ancestry audit | Static migration tests and single head pass. Live PG17/18 legs and complete earlier shipped-history compatibility audit UNVERIFIED. |

## Handoff — BLOCKED

Changed file: only `docs/testing/goal-1572-current-repair.md`. No production code, tests, inventory counts, gates, ledgers or grants changed. No test additions, hence no inventory-delta note is needed. Incoming work is preserved. This report is an evidence checkpoint, not a claim of repair or integration approval.

The permitted vulture repair has no reproduced defect. The actual reproduced lifecycle failure requires an independently landed authorization under `scripts/ratchet_provenance.py:478`; candidate grants cannot authorize themselves. That policy action is outside this lane. The named integration-scope failure remains UNRESOLVED without its exact-head failed specialized producer evidence; do not synthesize passing `--result` inputs. Docker is unavailable despite the environment brief, so PostgreSQL acceptance cannot be proved here.

Next: obtain the actual integration-scope failing producer log, independently land the lifecycle authorization, and provide working PG17/18 infrastructure before retrying remaining acceptance. The captured check-run records do not establish the reported aggregate's failing producer at this starting head. This is an external-prerequisite handoff: repeating the same repair dispatch without those prerequisites cannot repair the reproduced policy failure. No GitHub mutations or issue closure actions performed.

Progress: checked 1 assigned item; done 0 repairs; skipped 0 items; errors 1 policy blocker reproduced by gate and test, plus unavailable Docker infrastructure. Commit this evidence-only checkpoint locally and leave the worktree clean.
