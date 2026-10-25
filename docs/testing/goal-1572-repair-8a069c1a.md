# #1572 repair evidence — job 8a069c1a

## Frozen scope and disposition

- Assigned worktree `/home/dev/Git/wt/auto-1572`, branch `auto-1572`.
- Tested starting HEAD: `f631c901b581681397ae0b8ab5f7b8e7d9051f25`.
- Assigned develop base: `c4bd944393ad7944ac1593013a817b5b22e04dc8`.
- One item only: #1572, specifically evidenced integration-scope/vulture repair. Inspected Goal implementation, adjacent tests/composition/migration contracts, named CI scripts/workflows, supplied dispatch/prior artifacts and check-0..4 logs. No remote enumeration or GitHub mutations.
- Initial worktree was clean. Inherited unrelated differences against the assigned base were preserved, not repaired or reviewed as part of this lane.
- **BLOCKED:** no authorized in-branch fix for the reproduced lifecycle grant failure. No production, test, gate, grant or ledger changes are justified by the named scanner's results. This report is the only repository change; no test inventory delta is required.

## Fresh findings (not inherited verification claims)

1. `uv run python scripts/check-execution-lifecycles.py` exits 1: `maistro.goals.model::GoalStatus` is absent from the trusted base and has no already-landed authorization. The detector measured 19 classified versus 20 discovered lifecycles; trusted merge base `e46ad6708fda`, candidate `f631c901b581`. The same failure is reproduced by `tests/test_check_execution_lifecycles.py:374` (28 passed, 1 failed).
2. The requested CI-exact vulture command passes: 1326 reviewed identities, 1326 findings, zero unclassified. There is no unbanked identity to amend and no evidence for a dead-code repair.
3. `DOCKER_HOST=unix:///var/run/docker.sock docker info` exits 1: cannot connect to the daemon. No PostgreSQL service is available through the prescribed Docker endpoint. PostgreSQL test skips are not acceptance evidence.
4. Integration-scope is **not** the lifecycle gate. `scripts/check-integration-scope.py:20` aggregates nine specialized check names, not execution-lifecycles. The supplied dispatch check-run snapshots contain a `durable-events` failure and matching integration-scope failure at linked PR #1938 head `6d7458151b6224ac331c09f61514a8e6095f8f0c`; the other eight specialized checks succeeded at that head. Those are not check results for this lane's exact starting HEAD. No current-head producer failure log is supplied. Root cause of that durable-events failure is UNRESOLVED, not inferred from the separate lifecycle failure.
5. Local path classification against the assigned base requires all nine specialized checks. The aggregate evaluator, run **without fabricated results**, exits 1 listing all nine as missing. This proves incomplete local evidence, not a reproduction of the remote producer failure. Neither unrelated-head green checks nor the supplied local lint/test logs establish current-head integration-scope success.

## Architecture reconciliation

Read repository instructions and accepted ADR-032, ADR-081226-9944 and ADR-081426-1f7c. ADR-032 section 7 explicitly requires a previously landed grant for candidate-only lifecycle identities; DOMAIN classification does not exempt GoalStatus. `scripts/ratchet_provenance.py:478` loads authorizations from the trusted base. Neither the assigned develop authorization file nor the candidate contains a GoalStatus grant. The issue's Goal lifecycle requirement does not authorize weakening this accepted contract or adding a self-approving grant. No unresolved merge conflict exists; no fetch/merge or ref substitution was attempted.

Goal state remains separate from the canonical Graph -> Run -> NodeRun -> Attempt execution authority. Production uses the shared factory: Hive `packages/hive-conductor/backend/adapters/maistro_core.py:195` and server `packages/maistro-server/src/maistro_server/main.py:344` call `create_container`; `packages/maistro-core/src/maistro/container.py:2362,2648` wires/exposes the selected store and `:284` derives the Workspace-authorized seam. `goals/wiring.py` refuses an unmigrated PostgreSQL pool rather than silently selecting another backend. `runs/admission.py:136` forwards Goal provenance to canonical Run creation.

## Executed validation

Commands used long timeouts (1800 seconds for focused validation; 600 seconds for vulture/Docker probe). Raw logs and captured scope JSON are under `/home/dev/maistro/jobs/8a069c1a324e4b4fa5384214dd4dc8b5/worker-*`.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1326 findings, zero unclassified |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL; missing trusted-base GoalStatus authorization |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` | 55 passed, 16 skipped |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed at line 374 |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q` | 2 passed, 23 skipped |
| `uv run python scripts/check-m1-convergence-freeze.py --base c4bd944393ad7944ac1593013a817b5b22e04dc8` | PASS |
| `uv run python scripts/ci_merge_group_scope.py --json <captured triple-dot changed paths>` | All seven specialized legs required |
| `uv run python scripts/check-integration-scope.py --event-name pull_request --scope-json <captured scope> --required-json` | Nine required check names |
| Same aggregate command without `--required-json` or invented `--result` arguments | FAIL: all nine results missing locally |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3205 files |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info` | FAIL; daemon unavailable |

The supplied check-0..4 logs were inspected separately: dependency sync, Ruff, formatting and inventory passed; supplied focused tests passed 55/skipped 16. Inventory was not rerun because this repair changes no tests or counts.

## Acceptance map and limits

Test references below are under `packages/maistro-core/tests/goals/` unless stated otherwise. Bodies were inspected, not just test names/docstrings.

| Criterion | Fresh evidence / remaining gap |
| --- | --- |
| Goal and GoalRevision round-trip on three backends | `test_goal_store_conformance.py:171` passes memory/SQLite. PostgreSQL UNVERIFIED. |
| Append-only revisions, stale refusal, exactly one concurrent winner | Conformance `:195,230,277` passes memory/SQLite revision and terminal-transition cases. PostgreSQL UNVERIFIED. |
| Subgoal parent/Project lineage; explicit recorded owning-Agent transition | Conformance `:294,333` passes memory/SQLite, including invalid parent scope refusal and attributed old/new owners. PostgreSQL UNVERIFIED. |
| Admission binds immutable historical Goal provenance | `test_run_goal_binding.py:102,115` passes memory/SQLite admission, readback and Run terminal transitions. Half-bindings refused; Run outcomes leave Goal state unchanged. PostgreSQL and binding readback after a subsequent Goal revision are UNVERIFIED. |
| Two Workspace principals isolated; foreign indistinguishable from missing | Conformance `:398,472` passes memory/SQLite through `ScopedGoalStore`; canonical authorizer called by `goals/authorization.py:160`. PostgreSQL UNVERIFIED. |
| Shipped Container exposure and both production compositions | `test_goal_wiring.py:43,158` passes shared factory exposure and authorized seam use; Hive/server callers inspected above. Full durable application startup/restart for both products UNVERIFIED. |
| Restart durable composition with Goals/revisions and bound Run | `test_goal_restart_readback.py:36` passes SQLite store close/reopen, not full application restart. It advances the Goal before admission, so it does not prove historical binding after a later revision. PostgreSQL UNVERIFIED. |
| No GoalRun/OrchestratorRun/competing executor or product-private lifecycle | Convergence freeze PASS against assigned base. Separate lifecycle authorization gate FAIL, not waived by this result. |
| Preserve merged user-model 056/planner 057 identities and append fresh Goal migration | Two static installed-base tests PASS (including snapshot byte equality and Goal 062 after 061). Central allocation coordination UNVERIFIED. |
| Populated actual c560d4c/4675101 snapshots upgrade normally on PG17 and PG18 | Live migration tests skipped. Both PostgreSQL majors UNVERIFIED. |
| Upgraded Goal tables usable; user facts/keys/Run rows/planner artifacts preserved; reopened provenance | PostgreSQL upgrade/reopen assertions unexecuted; both majors UNVERIFIED. SQLite reopen is not a substitute. |
| Fresh install, unique/single head, downgrade/refusal, reapplication and older quota-door history | Static identity checks pass; live paths and complete historical compatibility audit UNVERIFIED. |

## Handoff

Checked: 1 issue. Done: 0 repairs. Blocked: 1. No speculative code or policy changes.

Required next inputs: an independently landed GoalStatus authorization and updated trusted base; exact-candidate durable-events/integration-scope producer logs; reachable PostgreSQL 17/18 infrastructure for skipped acceptance legs. This local evidence commit is not integration approval and does not close #1572.
