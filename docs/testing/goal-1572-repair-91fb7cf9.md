# Issue 1572 repair — job 91fb7cf9

## Frozen scope

- Sole issue: #1572; assigned branch/worktree: auto-1572, `/home/dev/Git/wt/auto-1572`.
- Starting HEAD: `52bdb09c05d834b9ab7ab46704bb6c8c32d13d0e`; dispatched develop base: `d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743`.
- Clean worktree confirmed before editing. Preserve all prior implementation.
- Process only supplied issue/PR evidence, Goal source/tests, corresponding Run binding and container wiring, migration tests, relevant ADRs, quality workflow/gates and this report. Potential write scope: this report, demonstrated Goal defects/tests with inventory notes, and (only for actual Vulture findings) `quality/vulture-baseline.json`. No grants or other quality ledgers may change.
- Ambiguity: dispatch names integration-scope and Vulture but prior blocker is lifecycle authorization. Reproduce these locally before deciding whether any code repair is warranted. No inferred remote green, no GitHub mutation or ref refresh.

## Initial evidence

Read repository AGENTS.md, dispatch issue body and prior result dd25afad. Driver check-0..4 logs: dependencies resolved, Ruff passes, format passes (3187 files), focused tests 55 passed / 16 skipped, core inventory passes (15659). These do not prove PostgreSQL acceptance or integration-scope readiness.

## Reproduced blockers and first gate results

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1326 reviewed / 1326 discovered; no unclassified or never-allowlist findings. No ledger amendment is warranted.
- `uv run python scripts/check-execution-lifecycles.py`: FAIL (exit 1), trusted merge base `66f3cea9e989`, 19 classified -> 20 discovered. `maistro.goals.model::GoalStatus` lacks already-landed authorization. CI exact command confirmed at `.github/workflows/quality.yml:1501`. This is a policy prerequisite, not dead code; changing/removing the enum to evade discovery is not a repair.
- Assigned develop base resolves. Its merge base with this branch is `66f3cea9e98980f146a12cf3142d66e30986d276`, not the dispatched develop tip. No conflict is present, so no conflict-repair sync is indicated.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`: FAIL (exit 1), cannot connect to daemon. Live PG17/18 validation remains unavailable.

## Focused validation

Executed again in this job, not inferred from previous reports:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3187 files).
- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q`: 55 passed, 16 skipped (2.78s).
- `uv run python scripts/check-m1-convergence-freeze.py --base d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743`: PASS.
- `uv run pytest tests/test_check_execution_lifecycles.py -x -q`: 28 passed, 1 failed at line 374, reproducing the missing GoalStatus trusted-base authorization.
- `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q`: 2 passed, 23 skipped. Do not report the skipped migration legs as passed.

Read accepted ADR-081426-b1d3 (Project scope), ADR-082826-d9f5 (canonical Run ownership) and ADR-091726-7c2a (interview-before-commit). No architecture change is appropriate: Goals remain domain desired state, Run/NodeRun/Attempt remain execution authority, and interview orchestration remains outside this issue. ScopedGoalStore delegates to WorkspaceAuthorizer rather than creating a competing policy authority.

The assigned develop snapshot's `quality/ratchet-authorizations.json` also has no GoalStatus entry. A sync to that snapshot cannot supply the missing prerequisite. No grant/ledger/gate edits are authorized here except demonstrated Vulture debt (none found).

Integration-scope is a separate specialized-check aggregator (`.github/workflows/integration-scope.yml`), not the lifecycle gate itself. The supplied captured check-runs name older PR heads, not this exact candidate. Therefore the actual merge-queue producer failure cannot be diagnosed from those results; do not attribute integration-scope to lifecycle without evidence.

## Integration evidence and inventory

Computed changed paths with `git diff --no-renames --name-only d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743...HEAD`, then ran `uv run python scripts/ci_merge_group_scope.py --json <measured paths>`. All seven scope legs are required. Ran `uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <computed JSON>`: exit 1, all nine required check results missing (docker-build, durable-events, both Hive E2E checks, MinIO, PG17, PG18, strike-ladder, wheel-imports). No fabricated `--result` values were supplied. This proves missing local evidence, NOT the cause of the previous remote merge-queue failure. Exact-head producer evidence is UNRESOLVED; obtain it before further code changes.

`uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 15659 unique identities, no duplicates. No tests added or changed, so no inventory delta is needed. `git diff --check`: PASS.

A lookup of `packages/hive-conductor/backend/app/adapters/maistro.py` returned not found; skipped that path. The actual shipped call is `packages/hive-conductor/backend/adapters/maistro_core.py:195`; server calls `create_container` at `packages/maistro-server/src/maistro_server/main.py:344`. Core wires the Goal backend at `packages/maistro-core/src/maistro/container.py:2362` and exposes it at line 2648. These source observations do not prove a deployed durable restart.

## Criterion-to-evidence map

| Acceptance | Executed evidence / boundary |
| --- | --- |
| Goal/GoalRevision round-trip on all backends | Shared `test_goal_store_conformance.py::test_goal_round_trips_through_the_backend` passes for memory/SQLite; PG skipped, therefore all-three criterion UNVERIFIED. |
| Append-only, stale revision refused, concurrent single winner; lifecycle finality | Shared conformance revision and lifecycle tests pass for memory/SQLite, including concurrent appends/transitions and terminal refusal. PG UNVERIFIED. |
| Subgoal parent/Project lineage and recorded ownership change | Shared conformance lineage and reassignment tests pass for memory/SQLite. PG UNVERIFIED. |
| Admission binding immutable after admission | `test_run_goal_binding.py` passes memory/SQLite admission read-back and terminal-transition preservation. PG skipped. Existing SQLite restart test binds revision 2 while Goal stays at revision 2: post-admission Goal revision advancement remains UNVERIFIED, despite its assertion message. |
| Workspace authorization, foreign indistinguishable from missing | Shared conformance scoped tests pass memory/SQLite against WorkspaceAuthorizer, including denied writes and same refusal type/message. PG UNVERIFIED. |
| Production wiring and shipped Container | `test_goal_wiring.py` passes actual Container exposure/authorized seam and backend refusal/selection tests; source paths above show both callers. Deployed Hive/server durable restart UNVERIFIED. |
| Durable Goal/revision/bound Run reopen | `test_goal_restart_readback.py` passes SQLite close/reopen; it constructs stores rather than restarting either product. PG composition restart UNVERIFIED. |
| No competing execution/Goal lifecycle authority | Convergence-freeze PASS; separate lifecycle policy gate FAILS for missing trusted-base authorization. Neither result cancels the other. |
| Preserve installed 056/057 migration identity and ancestry | Installed-base test module's two static identity/provenance tests pass. Live snapshot upgrades from c560d4c/4675101, preservation of existing facts/Runs/indexes/constraints, and durable read-back on PG17/18 are skipped and UNVERIFIED. |
| Fresh install, unique/single head, downgrade/refusal/reapplication, earlier supported ancestry | Database migration-chain legs skipped; complete supported-history compatibility and both-major upgrade matrix UNVERIFIED. |

## Disposition / handoff

BLOCKED. Only this evidence report changed; no speculative production, gate, grant, or ledger edits. No remote mutation performed. The observed lifecycle failure requires a separately landed trusted-base authorization, which this lane cannot grant itself. Vulture needs no repair. Integration-scope additionally requires exact-candidate specialized producer evidence; Docker service access is needed for the local PostgreSQL acceptance legs. Preserve existing work and resolve these prerequisites rather than rerunning the same policy failure or weakening discovery.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, blocked 1. Next: authorized owner lands lifecycle policy prerequisite; driver supplies exact-head specialized failure logs and available PG17/18 services. This report is committed locally; no integration approval is implied.
