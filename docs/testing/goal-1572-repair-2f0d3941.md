# #1572 repair checkpoint — 2f0d3941

## Scope and result

**BLOCKED; no justified source or vulture-ledger repair.** Only issue #1572
was processed in the assigned `auto-1572` worktree. Clean starting HEAD:
`bccddd8b85e1099be82927b5235cb0689425934b`; supplied develop snapshot:
`b90df19a24a1ce65a2fc686cffa6960fc2a7d6ff`; their merge base is
`e46ad6708fda20f76b8915679ef701f3ddb6b7e2`.

Read repository instructions, the frozen dispatch issue and driver check logs,
the supplied previous result, and accepted ADRs `ADR-092326-97c4` (shared
PostgreSQL Workspace authority) and `ADR-081426-1f7c` (mechanics-only runtime).
Inspected Goal authorization/wiring and adjacent admission/restart/migration
coverage. No conflicting architectural instruction was implemented: canonical
Workspace authorization and Goal -> Graph -> Run -> NodeRun -> Attempt remain
unchanged.

The lifecycle gate independently reproduces the prior blocker. Its trusted
base lacks authorization for `maistro.goals.model::GoalStatus` (19 classified,
20 discovered). Inspection of the supplied develop snapshot's
`quality/ratchet-authorizations.json` also finds no GoalStatus lifecycle grant;
its Goal-related Vulture grants do not authorize lifecycle debt. Syncing to
that snapshot alone cannot resolve this. This lane forbids lifecycle grant or
ledger amendments, and a same-branch grant would not authorize itself anyway.
Renaming GoalStatus or weakening the scanner is not a repair.

The specifically requested Vulture scan passes: 1,326 reviewed identities,
1,326 findings, zero unclassified. There is no evidenced identity to amend.

## First-hand commands and outcomes

Executed with long timeouts at the starting HEAD (only this report added
subsequently). Detailed test/gate outputs are `repair-*.log` under
`/home/dev/maistro/jobs/2f0d3941d880450a9d65ec74b04fd9e7/`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1326/1326; no ledger amendment warranted. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL: GoalStatus lacks already-landed authorization. |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed at line 374, same policy violation. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q -rs` | 55 passed, 16 PostgreSQL-dependent skips. |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q -rs` | 2 passed, 23 PostgreSQL-dependent skips. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3205 files already formatted. |
| `uv run python scripts/check-m1-convergence-freeze.py --base b90df19a24a1ce65a2fc686cffa6960fc2a7d6ff` | PASS: no unapproved new architecture island. |
| `uv run alembic heads` | PASS: single head `062`. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL: cannot connect to daemon. |
| `uv run python scripts/check-integration-scope.py --event-name pull_request` | FAIL CLOSED: nine missing specialized producer results. |

The last command is a local missing-evidence diagnostic, not a reproduction
of the remote producer failure. No producer successes were fabricated. The
integration workflow requires scoped specialized CI results; the standalone
lifecycle failure does not establish why that remote aggregation failed.
Remote integration-scope repair remains UNVERIFIED.

## Acceptance map

All test paths below are under `packages/maistro-core/tests/goals/` unless
otherwise stated. Skips are not passes.

| Criterion | Executed evidence and limitations |
| --- | --- |
| Goal and GoalRevision round-trip on memory/SQLite/PostgreSQL | `test_goal_store_conformance.py` round-trip passes on memory and SQLite; PostgreSQL UNVERIFIED. |
| Append-only revisions, stale revision refusal, exactly one concurrent winner | Shared revision/lifecycle/concurrent transition conformance tests pass on memory/SQLite; PostgreSQL UNVERIFIED. |
| Subgoal parent/Project lineage and recorded Agent reassignment | Shared lineage/reassignment tests pass on memory/SQLite; PostgreSQL UNVERIFIED. |
| Immutable Run admission binding and historical revision | `test_run_goal_binding.py` passes admission, storage, terminal transition and half-binding checks on memory/SQLite; PostgreSQL UNVERIFIED. Advancing a Goal revision after Run admission is not exercised by these executed tests: UNVERIFIED. |
| Workspace isolation and foreign equals missing | Shared scoped conformance tests pass on memory/SQLite through WorkspaceAuthorizer; PostgreSQL UNVERIFIED. |
| Production Container exposes canonical store in both products | `test_goal_wiring.py` real Container/seam and backend-selection checks pass. Live Hive/server durable composition startup/restart UNVERIFIED; schema-probe doubles are not PostgreSQL evidence. |
| Durable restart preserves Goal/revisions/bound Run | SQLite close/reopen in `test_goal_restart_readback.py` passes. This directly constructs stores; deployed Hive/server restart and PostgreSQL UNVERIFIED. |
| No competing GoalRun/executor/product-private lifecycle | Convergence freeze PASS against supplied develop snapshot. Separate lifecycle authorization gate FAILS. |
| Preserve merged user-model 056/planner 057 meaning/ancestry, append unused coordinated Goal identity | Two static installed-base tests pass, including historical bytes; Alembic has head 062. Central allocation coordination UNVERIFIED. |
| Populated actual c560d4c/4675101 forward upgrades without restamping/reset | Installed-base live upgrade tests skipped: PG17 and PG18 UNVERIFIED. |
| Upgrades preserve facts/statement keys/Run data/planner artifacts and enable durable Goal/revision/Run readback | Live tests skipped: both PostgreSQL majors UNVERIFIED. |
| Fresh install, unique identity/head, downgrade/refusal/reapplication, older quota-door history compatibility | Static identity checks and single head pass. Live chain tests and complete supported-history audit on both majors UNVERIFIED. |

## Handoff

Only this report changes. No tests were added or modified; inventory delta is
zero, so no new inventory note is needed. No code, grants, gates, ledgers or
migration identities changed. No GitHub mutations or destructive Git commands.

Next: obtain the separately landed lifecycle authorization through the owner
process, then sync and rerun; restore PostgreSQL validation infrastructure for
both supported majors; obtain actual specialized CI producer results. Do not
repeat cosmetic source/ledger edits or treat this handoff as integration
approval. Progress: checked 1 issue, done 0 repairs, skipped 0 issues, blocked 1.
