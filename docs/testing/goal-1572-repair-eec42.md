# Issue #1572 repair — eec42

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1572`, branch `auto-1572`.
- Starting head `964cf5a1e61f8aa402667e6268c479c746e7bee1`; supplied develop base `8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5`.
- Process only issue #1572. No remote mutations or re-enumeration of linked issues/PRs.
- Repair targets: reported integration-scope failure and explicit vulture per-identity ledger check. Candidate edit files frozen to this report and `quality/vulture-baseline.json` if the executed scanner identifies retained Goal-store identities. No grants or other ledgers may be edited.
- Inspect existing Goal implementation, related ADRs, adjacent tests and CI commands; execute focused validation. Record any actual source defect requiring a broader repair as unresolved rather than expanding this lane.

## Initial evidence

- Worktree clean; exact starting head confirmed.
- Read supplied dispatch issue body including seven original criteria and migration/installed-base clarifications.
- Driver logs: dependency sync passed; ruff check/format passed; Goal tests 55 passed, 16 skipped; core inventory 15797 matched. These are supplied observations, not independently reproduced acceptance evidence.
- Ambiguity: integration-scope failure has no subjob log in the supplied five deterministic logs. Proceed by executing the named vulture gate and the previously failing lifecycle gate with CI arguments.

## Validation

- Executed required CI-exact vulture scan: PASS, 1326 reviewed identities / 1326 findings, zero unclassified. No ledger repair justified.
- Executed `uv run python scripts/check-execution-lifecycles.py`: FAIL, 19 trusted versus 20 discovered lifecycles; `maistro.goals.model::GoalStatus` lacks already-landed trusted-base authorization. CI invokes this exact command at `.github/workflows/quality.yml:1508`.
- Actual gate base and `git merge-base HEAD origin/develop`: `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`, distinct from the supplied comparison base. No fetch or sync is needed to reproduce this finding.
- Executed `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`: FAIL, daemon unavailable. PostgreSQL service-backed acceptance cannot be claimed.
- Read accepted ADR-081226-9944, ADR-081226-a66b and ADR-092326-97c4. Goal desired state must remain distinct from canonical Run execution; no permission to disguise GoalStatus or change grants to bypass policy. Shared PostgreSQL remains the shipped durable authority.

## Focused validation results

All commands ran in the assigned worktree with 1000-second tool timeouts.

- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q -rs`: **55 passed, 16 skipped** (PostgreSQL DSN/database URL unset).
- `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q -rs`: **2 passed, 23 skipped** (live PostgreSQL unavailable).
- `uv run pytest tests/test_check_execution_lifecycles.py -x -q`: **28 passed, 1 failed**. `test_the_shipped_ledger_matches_the_shipped_code`, line 374, independently reproduces the missing GoalStatus authorization.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3205 files already formatted.
- `uv run python scripts/check-m1-convergence-freeze.py --base 8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5`: PASS, no unapproved architecture island.
- `uv run alembic heads`: PASS, single head `062`.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`: FAIL, nine specialized producer results missing (Docker, durable events, Hive backend/UI, MinIO, PG17/18, strike ladder, wheels). No scope/results were supplied; this only verifies fail-closed behavior locally, not the cause of the remote aggregation failure. Remote current-head integration-scope repair remains UNVERIFIED.
- `git diff --check`: PASS; final status before commit contains only this report.

## Acceptance review

Source/test inspection and executed evidence are distinguished below. PostgreSQL skips are not acceptance passes.

| Criterion | Current evidence |
| --- | --- |
| Goal/GoalRevision round-trip on all three backends | Shared `test_goal_store_conformance.py:171` passes memory/SQLite; PostgreSQL UNVERIFIED. |
| Append-only revisions, stale refusal, exactly one concurrent winner | Conformance tests at lines 197, 229, 278 pass memory/SQLite, assert frozen old content and one successful competing write. PostgreSQL UNVERIFIED. |
| Subgoal parent/Project lineage and recorded Agent change | Conformance tests at lines 294 and 333 pass memory/SQLite, reject foreign parents and inspect reassignment records. PostgreSQL UNVERIFIED. |
| Run admission binding and immutable historical revision | `test_run_goal_binding.py:102,115` passes admission/storage/terminal-transition preservation on memory/SQLite. PostgreSQL UNVERIFIED. Preservation after advancing the Goal revision post-admission is UNVERIFIED: these tests use fixed bindings. |
| Cross-Workspace principal isolation; foreign equals missing | Conformance tests at lines 398 and 472 pass memory/SQLite and compare refusal type/message. `goals/authorization.py` delegates VIEW/ADMINISTER to canonical WorkspaceAuthorizer. PostgreSQL UNVERIFIED. |
| Production Container exposes store | Real `create_container` tests in `test_goal_wiring.py` pass. Source calls are reachable from server `main.py:344` and Hive `backend/adapters/maistro_core.py:195`; Container selects store at `container.py:2362` and exposes it at line 2648. Actual durable startup/restart of both shipped products UNVERIFIED. |
| Durable restart preserves Goal/revisions/bound Run | `test_goal_restart_readback.py` passes SQLite close/reopen of raw stores. Not a Hive/server composition restart, and Goal revision is already 2 before Run admission. Product restart and PG17/18 UNVERIFIED. |
| No GoalRun, second executor or competing private lifecycle | Convergence gate passes at supplied base; separate lifecycle authorization gate still FAILS. |
| Preserve merged user-model 056/planner 057 and append unused migration | Both static installed-base tests pass, including byte comparison against actual merged snapshots and ancestry through 062. Central allocation coordination UNVERIFIED. |
| Populated c560d4c and 4675101 forward upgrades without resetting/restamping | Tests at `test_goal_installed_base_upgrade.py:469,493` skipped; both PG17/PG18 UNVERIFIED. |
| Upgrade preserves facts/keys/Run data, planner constraints/indexes, Goal tables and reopen provenance | Live installed-base tests skipped; both PG17/PG18 UNVERIFIED. |
| Fresh install, unique head/IDs, downgrade/refusal, reapplication and older quota-door ancestry audit | Single head and static ancestry pass. Live migration chain coverage, complete older-history audit and both supported PG major legs UNVERIFIED. |

## Disposition

BLOCKED. No source/test/ledger change is justified by the executed vulture scan. Removing or disguising GoalStatus would evade policy, not fix a demonstrated dead identity. The explicit vulture exception does not authorize lifecycle grants; trusted-base policy must be resolved independently before this lane can pass that gate.

Only this report changes in this round. No tests added; inventory delta zero, no new inventory note required. All incoming branch work is preserved. No remote fetch, push, merge or GitHub mutation performed.

Next: governance owner resolves the trusted-base GoalStatus authorization; restore PostgreSQL service availability for PG17/18 acceptance; obtain specialized producer evidence to diagnose the reported integration-scope failure. Do not infer remote producer failures from absent local inputs.

Progress: checked 1 item; done 0 repairs; skipped 0 items; blocked 1. This report is the committed handoff, not integration approval.
