# Issue 1572 repair — d99fe0bf

## Frozen scope

- Issue: #1572 only; assigned branch `auto-1572` in `/home/dev/Git/wt/auto-1572`.
- Starting HEAD: `9c16ede79c3ec6eef9e3e6c76de3e1a5b7bb3165`; dispatch base: `675db8be6c41b020ffffb224b2748c159c78a122`.
- Worktree clean on entry; no incoming edits to salvage.
- Evidence snapshot: dispatch-context.json, check-0.log through check-4.log in job `d99fe0bfe78e48f7aa47393dcd20b356`, and the supplied previous result.
- Candidate scope: existing Goal implementation/tests, relevant accepted ADRs, lifecycle and vulture gates; only evidence-supported repairs and this report. No unrelated inherited changes, grant edits, or GitHub mutations.

## Initial evidence and assumption

Driver logs report dependency sync, Ruff lint/format, 55 focused tests passed with 16 skipped, and suite inventory success (15797). These do not establish PostgreSQL acceptance or lifecycle authorization. Previous result reports a trusted-base GoalStatus authorization blocker. Integration-scope producer details were not supplied; assume the named lifecycle and vulture gates are the first reproducible checks, not that their earlier results remain current.

## Validation

Fresh CI-exact vulture gate passed: 1326 reviewed identities/findings, zero unclassified; no ledger amendment is justified. Fresh CI-exact lifecycle gate failed: `maistro.goals.model::GoalStatus` has no already-landed authorization (19 classified -> 20 discovered, trusted base `e46ad6708fda`, candidate `9c16ede79c3e`). `DOCKER_HOST=unix:///var/run/docker.sock docker info` failed: daemon unavailable. No production repair or test addition yet. These are actual command outcomes, not inherited claims.

Fresh tests: `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` passed 55, skipped 16. `uv run pytest tests/test_check_execution_lifecycles.py -x -q` failed at line 374 (28 passed), reproducing the missing grant. `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q` passed 2, skipped 23. Ruff check and format check passed (3205 files formatted). Command timeouts: 1800 seconds.

Read ADR-032 section 7: candidate-only lifecycle identities require an already-landed grant even when domain-classified. No in-branch grant, classification edit, or alternate representation of GoalStatus can legitimately resolve this blocker. Existing tests show Goal state is independent of Run outcome; that architecture does not waive the gate. No sync conflict exists and no evidence supplied indicates a grant landed after the frozen base. Direct `git show` inspection found zero `GoalStatus` mentions in `quality/ratchet-authorizations.json` at both the supplied base and its resolved merge base `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`; merging the supplied base cannot provide the missing grant.

`uv run python scripts/check-m1-convergence-freeze.py --base 675db8be6c41b020ffffb224b2748c159c78a122` passed. `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` passed: 15797 unique nodes, no duplicates. No tests changed, so no inventory delta is needed.

## Acceptance map

Paths below are under `packages/maistro-core/tests/goals/` unless stated otherwise. This map is based on fresh execution and inspected test bodies, not their docstrings.

| Acceptance | Evidence and remaining limits |
| --- | --- |
| Goal/GoalRevision round-trip across three stores | `test_goal_store_conformance.py:171` passed memory/SQLite. PostgreSQL skipped: UNVERIFIED. |
| Append-only, stale refusal, one concurrent winner | Conformance `:197,229,278` passed memory/SQLite. PostgreSQL and independent-connection race evidence UNVERIFIED. |
| Subgoal parent/Project; explicit recorded Agent reassignment | Conformance `:294,333` passed memory/SQLite, including foreign-parent refusal. PostgreSQL UNVERIFIED. |
| Run binding at admission; immutable historical revision | `test_run_goal_binding.py:102,115` passed memory/SQLite admission/readback/terminalization. PostgreSQL UNVERIFIED. The reopen test advances the Goal before admission, not after: preservation following a subsequent Goal revision remains UNVERIFIED. |
| Two Workspace principals isolated; foreign equals missing | Conformance `:398,472` passed memory/SQLite using `ScopedGoalStore` and the canonical Workspace authorizer. PostgreSQL UNVERIFIED. |
| Production wiring and Container exposure | `test_goal_wiring.py:43,158` passed factory exposure and authorized access. Hive adapter `backend/adapters/maistro_core.py:195` and server `maistro_server/main.py:344` call `create_container`; `container.py:2362,2648` wires/exposes the store. `test_goal_restart_readback.py` proves SQLite store reopen, not a full durable Hive/server restart: those application restart legs UNVERIFIED. |
| No competing execution authority | Fresh convergence freeze passed. Accepted ADR-081226-9944 and ADR-081426-1f7c inspected; Goal domain state remains separate from Run execution. This does not waive ADR-032 authorization. |
| Preserve merged migration 056/057 meaning and ancestry; append unused Goal identity | Two static installed-base tests passed, including historical byte equality. Goal migration is 062 after 061. Central allocation coordination UNVERIFIED. |
| Populated upgrades from actual c560d4c/4675101 snapshots | PostgreSQL tests skipped; PG17/18 normal forward upgrades without reset/stamp changes UNVERIFIED. |
| All Goal tables usable after upgrade, facts/keys/Runs/planner artifacts preserved, durable provenance reopened | Live PostgreSQL legs skipped; UNVERIFIED on both majors. SQLite reopen is not a substitute. |
| Fresh install, unique IDs/single head, downgrade/refusal, reapplication, earlier quota-door history compatibility | Static identity/graph tests passed; live migration and full supported-history audit UNVERIFIED. |

## Integration-scope and disposition

`.github/workflows/integration-scope.yml:67` resolves required specialized producer checks and then waits for their results. The supplied failure cannot be attributed to the separate lifecycle gate without same-candidate producer evidence. Its actual failed producer remains UNRESOLVED; no GitHub re-enumeration or mutation was performed. Do not claim integration-scope passes.

**BLOCKED.** No source, test, workflow, inventory, ledger, or grant edits were made. Only this report changed; existing implementation is preserved. The specifically permitted vulture repair is unnecessary because its exact gate already passes. Fixing the lifecycle gate legitimately requires an independently landed authorization, outside this lane's permissions. Docker unavailability additionally prevents mandatory live PostgreSQL acceptance.

Handoff: land the GoalStatus lifecycle grant separately through the authorized process, provide the updated trusted base and exact-candidate specialized CI results, and restore reachable PostgreSQL 17/18 infrastructure before rerunning blocked acceptance. No integration approval or closure claim.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: external authorization and acceptance infrastructure/evidence}. The error is the lifecycle policy failure, independently reproduced by its regression test. This report is committed locally.
