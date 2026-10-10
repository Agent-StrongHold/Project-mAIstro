# Issue #1572 repair — b1aa8e7b

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1572`, branch `auto-1572`.
- Starting head `21acad5767f3a437262c1f4f16210777842f9b79`; supplied develop base `0b13478d7e7e4b2e749cdc6467af620189fddbe9`.
- Process only issue #1572: reproduce integration-scope / execution-lifecycles and exact-debt-ledger failures; inspect existing Goal production paths and acceptance tests. No external issue enumeration or GitHub mutation.
- Candidate edit scope: this evidence report; `quality/vulture-baseline.json` only if the required scan identifies reviewed retained Goal identities. No grant or other ledger edits authorized.
- Initial tree clean; exact starting head verified. No salvage needed.

## Initial evidence

Read the complete issue body from the supplied dispatch snapshot. Driver logs report dependency sync, ruff check/format passing, Goal tests 55 passed / 16 skipped, and core inventory matching 15797 cases. These are driver observations, not independently reproduced acceptance proof.

Assumption: this is a writer repair lane. Previously reported missing trusted-base GoalStatus authorization must be reproduced before deciding whether an in-scope repair is possible. Migration and durable PostgreSQL criteria require real execution; skipped tests do not prove them.

## Reproduced blockers

Executed with 1000-second timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1326 reviewed / 1326 findings, zero unclassified. No vulture ledger amendment justified.
- `uv run python scripts/check-execution-lifecycles.py`: FAIL: `maistro.goals.model::GoalStatus` absent from trusted base with no already-landed authorization (19 classified / 20 discovered). CI command confirmed at `.github/workflows/quality.yml:1508`.
- `git merge-base HEAD origin/develop`: `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`, the gate's trusted base.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`: FAIL, daemon unavailable. Live PostgreSQL acceptance cannot be inferred from skips.

The lifecycle blocker is a trusted-policy prerequisite, not dead code. No authorized in-branch grant/ledger repair exists in this lane. No sync conflict exists. Further focused validation:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3205 files).
- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q -rs`: 55 passed, 16 skipped (PostgreSQL unset).
- `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q -rs`: 2 passed, 23 skipped (PostgreSQL unset).
- `uv run pytest tests/test_check_execution_lifecycles.py -x -q`: 28 passed, 1 failed at line 374; same missing GoalStatus authorization.
- Verified supplied base resolves, then `uv run python scripts/check-m1-convergence-freeze.py --base 0b13478d7e7e4b2e749cdc6467af620189fddbe9`: PASS.
- `uv run alembic heads`: PASS, single head `062`.

All above ran with 1000-second timeouts. Read accepted ADR-081226-9944, ADR-081226-a66b and ADR-092326-97c4. Reconciliation: Goal desired-state lifecycle does not replace the Run/NodeRun/Attempt execution spine; store-level SQLite reopen is not proof of the shipped shared-PostgreSQL products restarting. No architectural workaround for the gate is appropriate.

## Final checks and acceptance map

- `uv run python scripts/check-integration-scope.py --event-name merge_group`: FAIL, nine missing producer results. No fabricated results or narrowed scope supplied. This establishes incomplete local evidence, NOT the cause of the remote failure. The workflow aggregates specialized PostgreSQL/storage/events/strike/Hive/wheel/Docker checks; execution-lifecycles is not a producer (`scripts/check-integration-scope.py:20`). Exact-candidate failed producer evidence remains UNRESOLVED; no speculative repair warranted.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 15797 unique identities, no duplicate evidence.
- Parsed `quality/ratchet-authorizations.json` from the resolved supplied develop base via `git show`: no GoalStatus entry. Merging that snapshot would not supply the prerequisite.
- `git diff --check`: PASS.

| Acceptance criterion | Executed evidence / boundary |
| --- | --- |
| Goal/GoalRevision round-trip on all three backends | Conformance `test_goal_store_conformance.py:171` passes memory/SQLite. PostgreSQL UNVERIFIED. |
| Append-only, stale revision refusal, concurrent exactly-one winner, terminal finality | Conformance lines 197, 229, 278 pass memory/SQLite. PostgreSQL and independent SQLite writers UNVERIFIED (race uses one store instance). |
| Parent/Project lineage and recorded owning-Agent transition | Conformance lines 294, 333 pass memory/SQLite. PostgreSQL UNVERIFIED. |
| Immutable Run admission binding and historical revision | `test_run_goal_binding.py:102,115` passes memory/SQLite through real `admit_direct_work`, preserving binding through terminal transitions. Source admission passes paired provenance to canonical Run store. PostgreSQL and subsequent Goal revision advancement UNVERIFIED; existing tests use fixed revision values. |
| Workspace isolation and foreign indistinguishable from missing | Conformance lines 398, 472 pass memory/SQLite through `ScopedGoalStore`; `goals/authorization.py` delegates VIEW/ADMINISTER to WorkspaceAuthorizer. PostgreSQL UNVERIFIED. |
| Production composition exposes Goal store | `test_goal_wiring.py:44,162` passes real Container construction and authorized create/read/refusal. Source: server `main.py:344` and Hive `backend/adapters/maistro_core.py:195` call the factory; `container.py:2362,2648` wires/exposes the store. Live startup/restart of both shared-PostgreSQL products UNVERIFIED. |
| Durable restart of Goal/revisions and immutable bound Run | `test_goal_restart_readback.py:37` passes SQLite close/reopen of stores, not product processes. Goal remains revision 2 after admission, so post-admission revision-advance preservation is UNVERIFIED. PG17/18 product restart UNVERIFIED. |
| No competing executor/lifecycle | Convergence-freeze PASS at supplied base. Separate execution-lifecycle policy FAIL remains; a passing freeze does not override trusted authorization. |
| Preserve merged 056/057 and append unused identity | Two static tests in `test_goal_installed_base_upgrade.py:391` pass ancestry and byte equality to actual merged migrations (including HITL 061). Single head 062 verified. Central allocation coordination UNVERIFIED. |
| Populated actual c560d4c/4675101 upgrades without reset/restamp | Live snapshot tests at lines 469, 493 skipped; both PostgreSQL majors UNVERIFIED. |
| Goal tables, retained facts/keys/Runs, planner artifacts and durable readback after upgrade | Live installed-base tests skipped; PG17 and PG18 UNVERIFIED. |
| Fresh install, unique IDs/single head, downgrade/refusal, reapplication, older quota ancestry | Static graph and single-head checks pass. Live migration tests skipped; PG17/18 matrix and complete older shipped-history compatibility audit UNVERIFIED. |

## Committed handoff — BLOCKED

Only this report changed. No production, test, workflow, ledger or grant modifications; no tests added and inventory delta zero. Existing implementation preserved. No fetch, GitHub mutation, push or integration action performed.

An authorized owner must independently land the GoalStatus lifecycle authorization before this branch can consume it. Supply exact-candidate integration producer failure evidence and working PG17/18 infrastructure to resolve the remaining acceptance gaps. Relabeling the domain enum or self-authorizing would evade policy, not repair it.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors/blockers 1 policy prerequisite, plus unavailable PostgreSQL infrastructure and unresolved remote aggregate cause. This evidence-only commit is a handoff, not integration approval.
