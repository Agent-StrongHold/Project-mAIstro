# Issue #1572 repair checkpoint (92786)

## Frozen scope

- Assigned issue: #1572 only; branch `auto-1572`.
- Starting HEAD: `b7c85ef2c1021cb96ac907e381808295ff2d010b` (verified); supplied base: `d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743` (resolved by diff).
- Clean initial worktree; no salvage required.
- Inspect the supplied dispatch snapshot, five check logs, canonical Goal implementation and adjacent tests/ADRs, and CI gate configuration. Repair only evidenced integration-scope / vulture failures and related Goal acceptance failures.
- Potential edit scope: Goal implementation/tests, required test inventory note, explicitly permitted `quality/vulture-baseline.json`, and this report. No other ledger/grant edits.
- Ambiguity: generic prompt contains both verifier and writer instructions; explicit assigned repair and commit requirement select writer mode.

## Progress

Initial repository instructions read and exact starting ref verified. Supplied `check-0.log` through `check-4.log` report dependency sync, lint/format success, 55 passed / 16 skipped Goal/parity tests, and 15,659 core inventory entries. PostgreSQL acceptance is not proven by those skipped tests.

First-hand gate results:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,326 reviewed identities / 1,326 findings; no unbanked identities. No vulture ledger amendment is warranted.
- `uv run python scripts/check-execution-lifecycles.py`: FAIL, `maistro.goals.model::GoalStatus` is absent from trusted base and has no already-landed authorization (19 classified -> 20 discovered).
- Supplied develop ref and local `origin/develop` both resolve to `d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743`; actual merge base is `66f3cea9e98980f146a12cf3142d66e30986d276`.

The evidenced blocker is not vulture debt. Lifecycle grant/ledger edits are forbidden in this lane. No classification weakening or fabricated authorization is permitted. The frozen develop snapshot's authorization file also has no `GoalStatus` / `goals.model` match; merely syncing to that snapshot would not supply the prerequisite.

Additional first-hand results:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,187 files.
- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q`: 55 passed, 16 skipped.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`: FAIL, cannot connect to daemon. No PostgreSQL server was started and skipped legs are not passes.

Read accepted ADR-081226-a66b, ADR-082826-d9f5, ADR-092326-97c4 and ADR-091726-7c2a. The Goal domain lifecycle does not replace Run/NodeRun/Attempt; authorization delegates to WorkspaceAuthorizer; a configured PostgreSQL pool with missing Goal tables fails closed. Interview orchestration belongs to consumers, not a competing store. No ADR reconciliation requiring code changes was identified.

The restart test exercises fresh SQLite stores, not a restarted product process. Its Run binding uses revision 2 and the Goal remains at revision 2, so later-revision historical preservation is not proven by that assertion. These are acceptance evidence limitations, not demonstrated production defects or a reason to make speculative gate repairs.

## Final focused validation

- `uv run pytest tests/test_check_execution_lifecycles.py -x -q`: 28 passed, 1 failed at `tests/test_check_execution_lifecycles.py:374`. Same missing trusted-base GoalStatus authorization.
- `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q`: 2 passed, 23 skipped. Static migration identity/provenance checks pass; database upgrades do not run.
- `uv run python scripts/check-m1-convergence-freeze.py --base d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743`: PASS.
- Read the prior result artifact, but use the new executions above as current evidence.
- Source reachability confirmed: Hive adapter `packages/hive-conductor/backend/adapters/maistro_core.py:195` and server `packages/maistro-server/src/maistro_server/main.py:344` call `create_container`; core `container.py:2362` wires Goals and line 2648 exposes the store. This does not prove either product's durable restart.

## Integration-scope evidence boundary

Read `.github/workflows/integration-scope.yml`. This aggregates specialized check results, not the execution-lifecycles result. The frozen dispatch's captured check-run objects contain **zero** checks at the exact assigned head. The remote failure's cause remains UNRESOLVED; claiming Vulture or lifecycle caused it would be speculative.

Measured changed paths with `git diff --no-renames --name-only d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743...HEAD`, passed them to `uv run python scripts/ci_merge_group_scope.py --json`: all seven flags true. Executed `uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <computed JSON>` without inventing producer results: exit 1, nine required results missing (docker-build, durable-events, Hive backend/UI E2E, MinIO, PostgreSQL 17/18, strike-ladder, wheel-imports). This is missing local evidence, not proof of the remote failure's cause.

## Criterion-to-evidence map

| Acceptance criterion | Executed evidence and limitations |
| --- | --- |
| Goal/GoalRevision round-trip on all three backends | Shared conformance passes memory/SQLite; PostgreSQL skipped, all-three criterion UNVERIFIED. |
| Append-only revisions, stale update refusal, one concurrent winner | Shared conformance CAS and lifecycle tests pass memory/SQLite; PostgreSQL UNVERIFIED. |
| Subgoal parent/Project and explicit recorded Agent changes | Shared conformance lineage and reassignment tests pass memory/SQLite; PostgreSQL UNVERIFIED. |
| Run admission binding and immutable historical revision | Admission and terminal-transition binding tests pass memory/SQLite; later Goal revision advancement and PostgreSQL UNVERIFIED. |
| Cross-Workspace isolation, foreign equals missing | Scoped conformance through WorkspaceAuthorizer passes memory/SQLite; PostgreSQL UNVERIFIED. |
| Shipped Container and both production compositions | Actual Container exposure/authorized seam tests pass; both shipped callers verified in source; durable product restart UNVERIFIED. |
| Restart/read back Goal, revisions, bound Run | SQLite close/reopen test passes; no Hive/server process restart or PostgreSQL readback executed. |
| No competing scheduler/executor or Goal authority | Convergence freeze passes; independent lifecycle authorization gate still fails. |
| Preserve merged 056/057 meaning/ancestry, append fresh migration | Static identity/provenance tests pass, with Goals at 062 after HITL 061; external allocation coordination UNVERIFIED. |
| Actual populated c560d4c and 4675101 forward upgrades, data/index preservation, reopened durable provenance | Database tests skipped; UNVERIFIED on PostgreSQL 17 and 18. |
| Fresh install, unique single head, downgrade/refusal, reapplication, earlier quota-door histories | Static graph exercised by identity test; live migration-chain and supported-history compatibility UNVERIFIED on both majors. |

## Disposition and handoff

**BLOCKED.** Only this report changed. No production, test, workflow, ledger, or grant edits were justified by the evidence. No test additions means no inventory delta is required. The existing implementation is preserved.

The authorized owner must first land the GoalStatus policy prerequisite on the trusted base in a separate change. Exact-candidate specialized producer logs are needed to diagnose the remote integration-scope failure, and accessible PostgreSQL services are needed for the skipped acceptance matrix. No remote actions or Git merges were performed.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; blocked 1. Next: external policy authorization and exact-candidate CI evidence, then revalidation. This report is committed locally as a blocked handoff, not integration approval.
