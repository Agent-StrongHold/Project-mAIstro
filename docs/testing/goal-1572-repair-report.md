# Goal #1572 repair validation

## Frozen scope

- Issue: #1572 only; assigned worktree `/home/dev/Git/wt/auto-1572`.
- Starting head: `c5ec11d144d272321dcb9ca7c30f3f1f2acbb60c`.
- Supplied develop base: `b78637f52be33c53d49aca1aa5738e3ab820aad3`.
- Repair target: reported integration-scope failure; specifically execute the vulture per-identity gate and execution-lifecycle gate before deciding any repair.
- File scope: existing Goal implementation/tests/migration and directly implicated gate ledger, plus this validation report and inventory note if tests change. No unrelated issues, grants, or GitHub mutations.
- Initial worktree is clean; HEAD matches the assigned ref.
- Role assumption: writer (explicit repair assignment), not read-only verifier.

## Supplied evidence (not independent acceptance)

Job `9503568fa49243c889a1dfcc4dac8c4d` check logs: dependency sync, lint and formatting pass; selected tests report 46 passed / 16 skipped; core inventory reports 14961 tests. PostgreSQL/skipped legs require additional validation.

## Progress

First-hand CI-exact vulture gate passed: 1328 reviewed identities / 1328 findings, zero unclassified or forbidden. No ledger amendment is warranted.

First-hand `uv run python scripts/check-execution-lifecycles.py` failed: `maistro.goals.model::GoalStatus` is absent from the trusted base and has no already-landed authorization (19 classified / 20 discovered). Actual merge base is `9bd1a93eefc4e564041b3cc512f20b229cde64b9`, not the supplied newer develop ref. No conflict exists at entry; no sync was requested except for conflict resolution. The lifecycle grant cannot be added in this repair lane.

Read accepted hierarchy, Run lifecycle, schema-evolution, server Container and shared-PostgreSQL Workspace ADRs. No change to architecture or lifecycle representation is justified by this failure. Existing prior repair evidence also distinguishes integration-scope aggregation from lifecycle quality validation; attribution of the named aggregation failure still needs its producer log.

Executed focused core validation: `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` -> **1813 passed, 311 skipped, 6 warnings** (aiosqlite worker threads reaching a closed event loop in adjacent Run tests). Full output: job `repair-core.log`.

Docker probe (`DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`) failed: daemon unavailable. No PostgreSQL execution is claimed. Supplied develop authorization file has Goal field vulture grants but no GoalStatus lifecycle grant.

Source inspection confirms both shipped callers use `create_container` (server `main.py:344`, Hive `backend/adapters/maistro_core.py:194`); it wires Goals at `container.py:2377`. Goal conformance, authorization, binding, wiring and installed-base tests were read, not just counted. They do not prove deployed-process restart or historical provenance after a post-admission revision append.

## Remaining executed validation

| Command | Outcome |
| --- | --- |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed at line 374: shipped-ledger assertion reproduces missing GoalStatus authorization. Job `repair-lifecycle-tests.log`. |
| `uv run pytest tests/migrations -x -q` | 38 passed, 125 skipped. |
| `uv run python scripts/check-m1-convergence-freeze.py --base b78637f52be33c53d49aca1aa5738e3ab820aad3` | PASS. |
| `uv run alembic heads` | PASS: single head 061. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3145 files. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 14961 identities; no duplicate evidence. |
| `git diff --check` | PASS. |

## Acceptance map at the assigned candidate

| Criterion | Executed evidence and limits |
| --- | --- |
| Goal/GoalRevision round-trip on three backends | Shared `test_goal_store_conformance.py` passes memory/SQLite. PostgreSQL UNVERIFIED. |
| Append-only revisions, stale refusal, concurrent single winner, final terminal states | Shared conformance tests pass memory/SQLite. Concurrency uses a single store object; independent SQLite writers and PostgreSQL UNVERIFIED. |
| Subgoal parent/Project lineage and recorded Agent transition | Shared conformance tests pass memory/SQLite. PostgreSQL UNVERIFIED. |
| Run admission binding and immutable historical revision | `test_run_goal_binding.py` passes memory/SQLite admission and terminal-transition preservation. Post-admission Goal revision advance and PostgreSQL UNVERIFIED. |
| Cross-Workspace isolation; foreign equals missing | Conformance exercises real `WorkspaceAuthorizer` through `ScopedGoalStore`, memory/SQLite pass. PostgreSQL UNVERIFIED. |
| Production store composition and exposed Container | Real factory/seam tests pass; server/Hive factory callers confirmed in source. Both deployed-process compositions UNVERIFIED. |
| Durable restart readback | SQLite store connection close/reopen test passes with Goal/revisions/transitions/bound Run. Deployed Container/process restart and PostgreSQL UNVERIFIED. |
| No competing executor or product-private lifecycle | Convergence freeze passes against supplied base. Separate lifecycle policy gate fails. |
| Preserve merged 056/057 meaning/ancestry and append unused Goal identity | Graph and snapshot-byte tests pass; 061 follows 060, single head. Central reservation UNVERIFIED. |
| Actual c560d4c/4675101 populated PostgreSQL upgrades without restamping | Live tests skipped. PG17 and PG18 UNVERIFIED. |
| Tables, preserved user-model/Run data, planner artifacts, reopened durable provenance after each upgrade | Live tests skipped. Both majors UNVERIFIED. |
| Fresh install, downgrade/refusal, reapplication, unique IDs, older quota ancestry audit | Static graph/identity checks pass. Live PG17/18 legs and complete older-history compatibility audit UNVERIFIED. |

## Handoff: BLOCKED

Only `docs/testing/goal-1572-repair-report.md` changed. No production code, tests, inventory counts, ledgers, grants or gates changed. No test additions require an inventory delta. All incoming implementation work remains preserved.

The genuine lifecycle failure is policy, not unused code. `scripts/ratchet_provenance.py:478` reads authorizations from the base; candidate grants cannot authorize themselves. An authorized owner must independently land the GoalStatus grant before this branch can consume it. The supplied newer base also lacks that lifecycle grant, so merging it is not an evidenced repair.

The named `integration-scope` failure remains **UNRESOLVED**: `scripts/check-integration-scope.py:20-27` aggregates specialized PostgreSQL, storage, durable-event, strike, Hive, wheel and Docker checks, not the lifecycle gate. Driver logs do not supply its failing producer log. No aggregate success or causal attribution is inferred; do not change its gate speculatively.

Next: obtain exact failed specialized-check evidence and the independent lifecycle authorization; provide working PostgreSQL 17/18 infrastructure, then prove remaining acceptance. No GitHub mutations or closure actions performed.

Progress: checked 1 assigned item; done 0 repairs; skipped 0 items; errors 1 reproduced policy blocker (also reproduced by its test), plus unavailable Docker. Evidence-only checkpoint is committed locally; this is not integration approval.
