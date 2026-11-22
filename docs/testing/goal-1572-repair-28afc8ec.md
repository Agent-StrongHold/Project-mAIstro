# Issue #1572 repair — job 28afc8ec

## Frozen scope

- One assigned item: #1572, branch `auto-1572`, starting HEAD `7a2406a10366a4b11fc2566e96cea4e31891d31a`, supplied develop base `675db8be6c41b020ffffb224b2748c159c78a122`.
- Initial worktree clean. No incoming changes to salvage.
- Evidence snapshot: supplied dispatch-context.json and check-0.log through check-4.log; no GitHub enumeration or mutation.
- Process only Goal production modules/tests, adjacent run admission/composition, Goal migrations, named CI gates and their workflow definitions. Repair scope: this report and, only if the requested scanner provides evidence, `quality/vulture-baseline.json` or genuinely dead Goal code. No other ledger/grant edits.
- Ambiguity: prior lifecycle authorization blocker may still apply. Check current trusted-base evidence; do not infer it was resolved from earlier reports.
- Acceptance includes the issue's installed-base PostgreSQL migration clarification, not only the original seven checkboxes.

## Progress

Initial HEAD verified; issue body and branch file delta inspected. Driver check logs inspected: sync, Ruff lint/format, focused tests (55 passed, 16 skipped), suite inventory (15797) succeeded; skips are not acceptance proof.

Fresh `uv sync --locked --extra dev` succeeded. The requested CI-exact vulture scan passed with 1326 findings, zero unclassified; no ledger amendment is supported by evidence. Fresh `uv run python scripts/check-execution-lifecycles.py` failed: GoalStatus lacks already-landed authorization (19 classified -> 20 discovered; trusted base e46ad6708fda, candidate 7a2406a10366). Supplied base resolves and its authorization file has zero GoalStatus mentions. `DOCKER_HOST=unix:///var/run/docker.sock docker info` failed: daemon unavailable. No production or ledger changes made.

Fresh focused Goal/schema tests passed 55, skipped 16. Lifecycle gate regression failed at `tests/test_check_execution_lifecycles.py:374` (28 passed), reproducing the missing grant. Installed-base/chain migration tests passed 2, skipped 23. Ruff check and format check passed (3205 files); convergence freeze against the supplied base passed. All validation commands used 1800-second timeouts.

Accepted ADR-032 section 7 explicitly requires an already-landed authorization for candidate-only lifecycles; domain classification is not an exemption. ADR-081226-9944 and ADR-081426-1f7c preserve Workspace/Project ownership and the Run/NodeRun/Attempt execution authority. Reconciliation: issue permission to implement Goal domain state does not override the accepted gate authorization contract. No in-branch grant or scanner-evasion repair is permissible.

## Commands and outcomes

All commands ran in the assigned worktree, against the starting code (only this report changed).

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | Passed |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed: 1326 reviewed identities/findings |
| `uv run python scripts/check-execution-lifecycles.py` | FAILED: missing trusted-base GoalStatus authorization |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` | 55 passed, 16 skipped |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 1 failed, 28 passed |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q` | 2 passed, 23 skipped |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed: 3205 files |
| `uv run python scripts/check-m1-convergence-freeze.py --base 675db8be6c41b020ffffb224b2748c159c78a122` | Passed |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Passed: 15797 unique test identities |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info` | FAILED: daemon unavailable |

## Acceptance evidence

Test paths in the table are under `packages/maistro-core/tests/goals/` unless stated otherwise. Tests were executed and their bodies inspected; docstrings alone are not treated as evidence.

| Criterion | Executed evidence / limits |
| --- | --- |
| Goal/GoalRevision round-trip on all three stores | `test_goal_store_conformance.py:171` passed memory/SQLite. PostgreSQL skipped: UNVERIFIED. |
| Append-only revisions, stale refusal, exactly one concurrent winner | Conformance `:197,229,278` passed memory/SQLite. PostgreSQL and independent-connection races UNVERIFIED. |
| Subgoal parent/Project lineage and recorded owning-Agent changes | Conformance `:294,333` passed memory/SQLite, including missing/foreign parent refusal and preserved parent. PostgreSQL UNVERIFIED. |
| Admission binds immutable historical Goal provenance | `test_run_goal_binding.py:102,115` passed memory/SQLite admission, readback and terminal transitions. `runs/admission.py:136` forwards the fields to canonical Run creation. PostgreSQL UNVERIFIED. Existing restart test advances the Goal before admission; historical binding after a subsequent Goal revision remains UNVERIFIED. |
| Workspace authorization and foreign equals missing | Conformance `:398,472` passed memory/SQLite through `ScopedGoalStore`; `goals/authorization.py:160` calls the canonical Workspace authorizer. PostgreSQL UNVERIFIED. |
| Both production compositions expose Goal store; durable restart | `test_goal_wiring.py:43,158` passed shared factory exposure and authorized seam access. Hive `backend/adapters/maistro_core.py:195` and server `maistro_server/main.py:344` call that factory; `container.py:2362,2648` wires/exposes the store. `test_goal_restart_readback.py` passed SQLite store reopen, not a full Hive/server restart. Both durable application restart legs UNVERIFIED. |
| No competing executor or product-private Goal lifecycle | Fresh convergence freeze passed; accepted execution/ownership ADRs inspected. Domain classification does not waive lifecycle authorization. |
| Preserve merged user-model 056/planner 057 identities and ancestry; append unused Goal migration | Two static installed-base tests passed, including snapshot byte equality and Goal 062 after 061. Central allocation coordination UNVERIFIED. |
| Populated PostgreSQL upgrades from actual c560d4c and 4675101 snapshots, no stamp editing/reset during forward upgrade | Live tests skipped. Both PG17 and PG18 UNVERIFIED. |
| Upgraded Goal tables usable, user facts/statement keys/Run rows and planner artifacts preserved; reopened Goal/revision/Run provenance | Live PostgreSQL tests skipped. Both majors UNVERIFIED; SQLite store reopen is not a substitute. |
| Fresh install, unique IDs/single head, supported downgrade/refusal and reapplication; earlier quota-door ancestry audit | Static migration graph/identity checks passed. Live coverage and complete supported-history compatibility audit UNVERIFIED. |

## Integration-scope and handoff

The supplied `integration-scope: failure` has no same-candidate failed-producer output in the inspected check logs. The frozen dispatch check-run extraction supplied no integration-scope record. `.github/workflows/integration-scope.yml:67` computes required producers and `:140` fails on an unsuccessful required check. Its actual failed producer remains UNRESOLVED; do not attribute it to the separate lifecycle gate without evidence or claim local convergence success establishes aggregation success.

**BLOCKED.** The current actual failure is the lifecycle authorization contract, independently reproduced by its test. An authorized owner must land the GoalStatus grant separately, then supply an updated trusted base for this lane. No unresolved develop-sync conflict exists. No fetch/merge was attempted because the supplied base contains no GoalStatus grant and no new authorized ref was supplied. Restore PostgreSQL 17/18 infrastructure and supply exact-candidate specialized CI evidence for the remaining acceptance legs.

Changed file: this report only. No source, test, workflow, inventory, ledger, or grant changes; no new tests means no inventory delta. No GitHub mutations. Existing implementation and inherited branch changes preserved. This report is committed locally; it is not integration approval.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: independently landed lifecycle authorization, PostgreSQL acceptance infrastructure, exact-candidate integration evidence}.
