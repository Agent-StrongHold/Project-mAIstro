# Issue #1572 repair validation

## Frozen scope

- Assignment: issue #1572, branch `auto-1572`, starting HEAD `34796dead610156dcd142bb45805324636f3132b`, supplied develop base `e3233939343b43249aa65a32b6d3b3aeb35d4dc5`.
- Process only the supplied dispatch snapshot; no GitHub mutations or re-enumeration.
- File scope: existing #1572 Goal-store implementation/tests and relevant ADRs (inspection); `quality/vulture-baseline.json` only if the explicitly assigned CI repair produces retained unbanked identities; this validation record. Any evidenced production repair and inventory note will be recorded here before editing.
- Role ambiguity resolved as writer: lane explicitly assigns repair and requires local commit.
- Initial worktree clean and HEAD matches assignment. Driver check logs: dependency sync, ruff lint/format pass; targeted tests 55 passed / 16 skipped; core inventory 14970 passes. These are driver evidence, not independent validation.

## Results

- Exact assigned vulture scan passes: 1,328 findings / reviewed identities, zero unclassified. No ledger amendment is justified.
- CI-exact `uv run python scripts/check-execution-lifecycles.py` fails: `maistro.goals.model::GoalStatus` absent from trusted-base policy with no already-landed authorization (19 -> 20, merge base `9bd1a93eefc4`). Supplied develop base also has no GoalStatus grant. No conflicts or sync repair is in progress; merging cannot supply the missing grant from that base.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info` fails to connect to the daemon. Live PG17/18 validation is blocked, not passed.
- Prior result artifact read. It reported the same policy and infrastructure blockers; these have now been independently reproduced. No gate evasion or candidate grant edit is permitted.
- Independent ruff lint and format checks pass (3,145 files). Goal suite plus SQLite Alembic parity: 55 passed / 16 skipped. Lifecycle gate tests: 28 passed / 1 failed at `tests/test_check_execution_lifecycles.py:374`, reproducing the policy blocker. Goal installed-base and migration-chain tests: 2 passed / 21 skipped. `uv run alembic heads`: single head 061. Convergence freeze against supplied develop SHA passes.
- Inspected accepted ADR-081226-9944, ADR-081226-a66b, ADR-092326-97c4 and ADR-087: ownership, canonical execution, shared durable authority/fail-closed, additive schema evolution remain governing. No conflicting issue instruction requires reconciliation or an alternate authority.
- Production reachability: server `main.py:344` and Hive `backend/adapters/maistro_core.py:194` call `create_container`; `container.py:2378` wires Goal storage and `:284` exposes the canonical Workspace-authorized seam. Live product restart remains unexecuted.
- `scripts/check-integration-scope.py:20` aggregates specialized PG, object-storage, events, E2E, wheel and Docker checks; it does not aggregate the lifecycle gate. Must not misreport that policy failure as the identified integration producer failure. Exact-head producer evidence remains unresolved. Inspected captured check-run records: failures concern other supplied heads and contain no producer log for starting HEAD `34796dead610`; no fabricated aggregate inputs were submitted.

## Executed commands

All commands ran in the assigned worktree with 600–1200 second command timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,328 identities |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL, missing trusted-base GoalStatus authorization |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info` | FAIL, daemon unavailable |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,145 files |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` | 55 passed, 16 skipped |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed |
| `uv run python scripts/check-m1-convergence-freeze.py --base e3233939343b43249aa65a32b6d3b3aeb35d4dc5` | PASS |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q` | 2 passed, 21 skipped |
| `uv run alembic heads` | PASS, 061 only |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 14,970 unique cases |
| `git diff --check` | PASS |

## Acceptance map (this execution only)

Test paths below are relative to `packages/maistro-core/tests/goals/` unless stated otherwise. Skips are not evidence of acceptance.

| Criterion | Evidence / limit |
| --- | --- |
| Goal and revision round-trip, three backends | `test_goal_store_conformance.py:171` passed memory/SQLite; PostgreSQL UNVERIFIED. |
| Append-only, stale CAS refusal, exactly one concurrent winner | Conformance tests at lines 197 and 278 passed memory/SQLite; PostgreSQL and independent durable writer race UNVERIFIED. Existing races share a store object. |
| Subgoal parent/Project and recorded Agent change | Conformance lines 294 and 333 passed memory/SQLite; PostgreSQL UNVERIFIED. |
| Run admission binding, immutable historical revision | `test_run_goal_binding.py:102,115` passed memory/SQLite admission and terminal-transition preservation. Actual Goal revision advancement after admission and PG UNVERIFIED; tests use fixed revision values. |
| Workspace isolation, foreign indistinguishable from missing | Conformance lines 398 and 472 passed memory/SQLite through `ScopedGoalStore` and canonical `WorkspaceAuthorizer`; PostgreSQL UNVERIFIED. |
| Shipped Container exposes store, both production compositions | `test_goal_wiring.py` passes non-PG legs; inspected both actual product factory callers and shared Container. Live durable Hive/server compositions UNVERIFIED. |
| Restart reads Goals/revisions and bound Run provenance | `test_goal_restart_readback.py:36` passed SQLite close/reopen of stores. Actual product restart and PG UNVERIFIED; Goal revision is not advanced after admission in this test. |
| No second executor, GoalRun or private lifecycle | Convergence freeze passes against supplied base. Lifecycle policy authorization remains separately blocked. |
| Preserve installed 056/057 identities and ancestry; append coordinated unused identity | Installed-base static identity and byte-provenance tests pass; Alembic single head 061. Central allocation coordination UNVERIFIED. |
| Populated actual c560d4c and 4675101 snapshots upgrade without restamping | PG17/18 UNVERIFIED; live tests skipped. |
| Post-upgrade Goal tables, preserved user facts/keys/Run data, planner artifacts, head, reopen provenance | PG17/18 UNVERIFIED; live tests skipped. |
| Fresh install, unique IDs/single head, downgrade/refusal, reapplication, older quota-door histories | Single head and static identity checks pass; fresh install, live downgrade/reapplication, complete older-history compatibility audit PG17/18 UNVERIFIED. |

## Final handoff

**BLOCKED.** Only this validation report changed. No production code, tests, grants or ledgers changed; no inventory delta is needed. Existing implementation is preserved. No push, remote mutation or issue action occurred.

The requested vulture repair has no failing evidence to repair. The independently reproduced lifecycle blocker requires an already-landed authorization through its authorized owner, not a candidate grant or disguised vocabulary. Supply the exact-head integration-scope producer failure logs and working PG17/18 infrastructure before attempting that repair or claiming full acceptance. Neither a clean vulture scan nor passing SQLite tests establish integration-scope success.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: "trusted-base GoalStatus authorization, exact-head failed integration producer evidence, and PG17/18 validation"}`. Commit this report locally; issue remains unresolved.
