# Issue #1572 repair checkpoint

## Frozen scope

- Assigned writer worktree `/home/dev/Git/wt/auto-1572`, branch `auto-1572`.
- Starting HEAD `039198de6b2aabfbc86c04e1c85bac0a7f0223f8`; assigned base `f11dfd0c559225b64098252677e843f23c3be299`.
- One item: issue #1572 canonical Goal store, specifically evidenced integration-scope/vulture repair. No other issues or PRs will be processed or refreshed.
- Initial working tree was clean. Dispatch context is the frozen evidence snapshot in job `7ff341cd9f1244969b9beb275fd8e251`.
- File scope: Goal implementation and adjacent tests/composition/migrations for inspection; `quality/vulture-baseline.json` for the explicitly authorized repair; this report and inventory note only if tests change. No other ledger/grant edits.

## Interpretation

Writer instructions apply (not the verifier-only no-edit instruction). Prior claims are unverified until reproduced. Migration acceptance includes real historical PostgreSQL upgrades, not backward stamping. No remote mutations or new issue discovery.

## Progress

- Confirmed exact starting HEAD and clean worktree; read repository instructions and primary issue body from frozen dispatch.
- Driver logs inspected: dependency sync, ruff lint/format passed; focused tests reported 55 passed / 16 skipped; core inventory matched 15,448 nodes. These are driver observations, not substituted for fresh validation.
- Fresh CI-exact vulture command passed: 1,328 reviewed identities = 1,328 findings, no unbanked identities. No evidence warrants a vulture ledger amendment.
- Fresh `uv run python scripts/check-execution-lifecycles.py` FAILED: `maistro.goals.model::GoalStatus` absent from trusted base with no already-landed authorization (19 -> 20). Trusted merge base is `bbc35234556c8802dd617daf23d9029cc2851045`, also the merge base against the assigned develop SHA. Prior blocker is reproduced.
- Initial convergence-freeze invocation omitted required `--base` and returned usage error; rerun with validated assigned base PASSED.
- Docker probe at prescribed socket FAILED: daemon unavailable. Live PostgreSQL evidence cannot currently be executed through Docker.
- Initial focused pytest command misspelled `test_sqlite_alembic_schema_parity.py` and collected no tests (exit 4); corrected command passed (details below). This is a command error, not an implementation failure.
- Read accepted hierarchy/runtime ADRs and interoperability ontology; Goal domain state must remain distinct from Run terminality. No change to that architecture or its gates is justified.
- Read prior result/report; it ends at this starting HEAD and records the same lifecycle blocker and unavailable Docker. Those two failures are now independently reproduced.
- Assigned base comparison contains unrelated historical differences. This repair will not rewrite or discard them. Only Goal acceptance and the assigned gate repair remain in scope.

## Fresh validation checkpoint

- Focused core acceptance plus adjacent Run/graph tests: **1,916 passed, 328 skipped, 6 warnings**, exit 0 (`/tmp/1572-7ff-core.log`). Warnings concern aiosqlite callbacks on closed event loops.
- Lifecycle regression: **28 passed, 1 failed**, `tests/test_check_execution_lifecycles.py:374`; same missing trusted-base GoalStatus authorization.
- Migration suite: **38 passed, 125 skipped**; live PostgreSQL acceptance remains unproven.
- `uv run ruff check .` and `uv run ruff format --check .`: PASS (3,170 files).
- `uv run alembic heads`: single head `061`.
- Existing tests reviewed: shared conformance, factory wiring, Run binding, SQLite reopen, actual historical snapshot migration fixtures. No test added or changed; no inventory delta is required.
- Historical migration identity/byte-equality tests explicitly rerun: **2 passed**, no skips.
- Core suite inventory rerun: PASS, 15,448 unique nodes, no duplicate evidence.
- Supplied develop authorization file contains no GoalStatus entry. `scripts/ratchet_provenance.py:478-504` explicitly loads grants from the trusted base; adding one on this branch cannot authorize itself.
- Frozen dispatch check-run records contain no exact-starting-HEAD check runs. The linked historical `c52c7872` record says integration-scope succeeded (other checks failed); it cannot identify the reported merge-queue producer failure. `.github/workflows/integration-scope.yml:76-157` aggregates specialized remote check evidence. Exact-candidate producer failure remains UNRESOLVED; do not substitute a local policy test or lifecycle failure for that evidence.

## Executed command record

Commands below used 600/1,200-second validation timeouts:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/check-execution-lifecycles.py
uv run python scripts/check-m1-convergence-freeze.py --base f11dfd0c559225b64098252677e843f23c3be299
DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'
uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py packages/maistro-core/tests/test_container_chat_runs.py -x -q
uv run pytest tests/test_check_execution_lifecycles.py -x -q
uv run pytest tests/migrations -x -q
uv run pytest tests/migrations/test_goal_installed_base_upgrade.py::TestTheMergedIdentities -q
uv run ruff check .
uv run ruff format --check .
uv run alembic heads
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
```

Outcomes are recorded above, including two corrected command-entry errors. No database environment was supplied to these commands; skipped PostgreSQL tests are not passing evidence.

## Acceptance map

Test paths below are relative to `packages/maistro-core/tests/goals/` unless stated otherwise.

| Criterion | First-hand evidence and limits |
| --- | --- |
| Goal/GoalRevision round-trip across three backends | `test_goal_store_conformance.py:171` passed memory/SQLite; PostgreSQL UNVERIFIED. |
| Append-only, stale revision refusal, concurrent exactly-one winner | Conformance `:197,229,278` passed memory/SQLite, exercising append and terminal-transition races. PostgreSQL and independent-connection races UNVERIFIED. |
| Subgoal parent/Project lineage and recorded Agent changes | Conformance `:294,333` passed memory/SQLite; invalid parent scope refused and transitions name old/new owner. PostgreSQL UNVERIFIED. |
| Run admission binding and immutable historical revision | `test_run_goal_binding.py:102,115` passed memory/SQLite admission and binding preservation through terminal transitions; half-bindings refused and Run outcome leaves Goal active. PostgreSQL and advancing the Goal revision after Run admission UNVERIFIED. |
| Two Workspace principals isolated; foreign equals missing | Conformance `:398,472` passed memory/SQLite through `ScopedGoalStore`; checks exception type/message and no refused writes. PostgreSQL UNVERIFIED. |
| Production Container wiring, Hive and server | `test_goal_wiring.py:43,158` passed actual factory exposure and authorized writes. Production callers inspected at Hive `backend/adapters/maistro_core.py:195` and server `maistro_server/main.py:344`; both call this factory. `container.py:2362,2648` wires/exposes the selected store; `:284` derives the Workspace-authorized seam. Durable application startup/restart UNVERIFIED. |
| Durable Goal/revision/bound Run readback | `test_goal_restart_readback.py:36` passed SQLite close/reopen. This uses fresh stores, not a restarted Hive/server process; its Project fixture is in-memory. PostgreSQL and deployed process restart UNVERIFIED. |
| No second executor or product-private Goal lifecycle | Convergence freeze PASSED against assigned base. Separate lifecycle policy gate FAILED and is not waived. Accepted ADR hierarchy/runtime contracts remain unchanged. |
| Preserve merged 056/057 meaning and ancestry; unused appended Goal ID | Two static installed-base tests PASSED, including byte identity against actual c560d4c/4675101 snapshots. Alembic has single head 061 after 060. Central allocation coordination UNVERIFIED. |
| Populated actual historical PostgreSQL upgrades with no stamp rewrite | PG17/PG18 installed-base tests SKIPPED; UNVERIFIED. |
| Goal tables usable after upgrades, old facts/keys/Runs/planner artifacts survive, reopen provenance | Live PG17/PG18 UNVERIFIED. Existing durable-reopen migration test covers planner snapshot only, not both snapshots. |
| Fresh install, unique IDs/single head, downgrade/refusal/reapplication, older quota ancestry audit | Static migration checks passed; live PG17/PG18 and complete supported-history compatibility UNVERIFIED. |

## Handoff

Verdict: **BLOCKED**. Only this evidence report changed; source, tests, workflows and all ledgers/grants are untouched. A cosmetic or speculative vulture amendment would not fix the reproduced failure.

Required next inputs: independently landed GoalStatus authorization in the trusted base; exact-candidate integration-scope producer logs; reachable PostgreSQL 17/18 test infrastructure. No merge conflict exists here and no sync was attempted. Inherited unrelated differences against assigned develop remain unreviewed and preserved. No integration approval or issue-closure claim.

Progress: checked 1 assigned item; done 0 repairs; skipped 0 items; errors 2 confirmed blocker categories (trusted-base authorization, unavailable Docker); next: resolve prerequisites outside this restricted repair, then rerun acceptance. All progress will be committed locally.
