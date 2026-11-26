# Goal #1572 repair — e9f5

## Frozen scope

- Assigned issue: #1572 only; branch `auto-1572`, worktree `/home/dev/Git/wt/auto-1572`.
- Starting candidate: `a8458d41806597e247b4f105e1ed9151fbae712b`.
- Supplied develop base: `af799688335f9a7dba7999a05e0e13f102c6c5ae`.
- Starting worktree was clean. No GitHub mutations or history replacement.
- Inputs frozen: supplied dispatch-context.json, check-0.log through check-4.log,
  prior b548 result if present. No re-enumeration of issues or PRs.
- Files in scope: canonical Goal implementation/tests, Run binding/composition,
  migration 061 and installed-base tests, relevant ADRs/gate scripts/workflows,
  this report and inventory notes; quality/vulture-baseline.json only under the
  explicit exact-debt-ledger repair permission. No other ledger/grant edits.

## Initial evidence and assumptions

Driver logs report ruff success and 55 passed/16 skipped Goal tests; these do not
prove PostgreSQL acceptance. Will execute additional checks locally.
`git diff --stat <supplied-base>..HEAD` includes substantial unrelated deletions
(e.g. failpoint tests and Hive scheduler tests). Preserve these inherited changes;
this focused repair does not authorize reverting or claiming them reviewed.
Integration-scope failure has no detailed log supplied. Assume the explicit
vulture gate and previously blocked lifecycle gate are the immediate reproductions;
record other discovered failures rather than guessing repairs.

## Execution results

- Exact vulture gate PASS: 1,328 reviewed identities match 1,328 findings,
  zero unclassified. No ledger amendment is justified by this result.
- Exact lifecycle gate FAIL: GoalStatus lacks already-landed authorization;
  trusted base is `bbc35234556c`, 19 classified -> 20 discovered lifecycles.
- Docker probe FAIL at the prescribed socket: daemon unavailable. No configured
  database environment was present. Live PG17/PG18 acceptance remains unavailable.
- Read prior b548 result/report; independently reproduced these blockers rather
  than accepting the earlier claims. No sync conflict exists in this worktree.
- Integration-scope is an aggregator over specialized producer checks, not the
  lifecycle/vulture gate. Its failure alone does not justify a code repair;
  frozen dispatch input contains zero check runs for the exact starting head.
  Producer failure is UNRESOLVED; no remote re-enumeration performed.
- Focused core tests: 1,916 passed, 328 skipped, 6 warnings (aiosqlite callbacks
  on closed event loops); `/tmp/1572-e9f5-core.log`.
- Lifecycle regression: 28 passed, 1 failed at
  `tests/test_check_execution_lifecycles.py:374` (same missing authorization).
- Migration tests: 38 passed, 125 skipped. Live database evidence not established.
- Ruff check/format PASS (3,170 files), convergence freeze PASS against supplied
  base, Alembic single head `061`.
- No GoalStatus match in supplied develop's ratchet-authorizations.json. Actual
  merge base with that develop is `bbc35234556c8802dd617daf23d9029cc2851045`.
- Read accepted ADR-081226-9944, ADR-081226-a66b, ADR-087,
  ADR-082426-2192, ADR-092326-97c4. Preserve shared durable authority and the
  canonical execution spine. No ADR reconciliation or gate weakening justified.

## Commands and outcomes

Validation used 1,200-second tool timeouts (inspection/probes 120 seconds).

| Command | First-hand outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,328 findings, zero unclassified. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL; GoalStatus needs trusted-base authorization. CI-exact invocation at quality.yml:1501. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL; daemon unavailable. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py packages/maistro-core/tests/test_container_chat_runs.py -x -q` | 1,916 passed / 328 skipped / 6 warnings; `/tmp/1572-e9f5-core.log`. |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed / 1 failed at line 374. |
| `uv run pytest tests/migrations -x -q` | 38 passed / 125 skipped. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS; 3,170 files. |
| `uv run python scripts/check-m1-convergence-freeze.py --base af799688335f9a7dba7999a05e0e13f102c6c5ae` | PASS. |
| `uv run alembic heads` | PASS; single head 061. |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py::TestTheMergedIdentities -q` | 2 passed; historical-byte equality actually executed, not skipped. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS; 15,448 unique identities, no duplicate evidence. |
| `git diff --check` | PASS. |

## Acceptance and reachable behavior

Paths in the table are relative to `packages/maistro-core/tests/goals/` unless
otherwise specified. No skipped test counts as proof.

| Criterion | Executed evidence / limits |
| --- | --- |
| Goal/GoalRevision round-trip on three backends | `test_goal_store_conformance.py:171` passes memory/SQLite, including revision conditions and author. PostgreSQL UNVERIFIED. |
| Append-only, stale revision refusal, concurrent one-winner | Conformance lines 197, 229, 278 pass memory/SQLite for concurrent appends and terminal transitions. Independent-writer races and PostgreSQL UNVERIFIED. |
| Subgoal parent/Project lineage and recorded Agent reassignment | Conformance lines 294, 333 pass memory/SQLite: invalid scope refused, parent unchanged, reassignment history names both Agents. PostgreSQL UNVERIFIED. |
| Run admission binding and immutability | `test_run_goal_binding.py:102,115` passes admission/persistence and unchanged binding through terminal transitions; half-bindings refused, Run outcome does not change Goal state. Goal revision advancement after admission and PostgreSQL UNVERIFIED. |
| Two principals/two Workspaces isolated; foreign equals missing | Conformance lines 398, 472 pass memory/SQLite through ScopedGoalStore/WorkspaceAuthorizer; exception type/message compared and refused mutations leave history unchanged. PostgreSQL UNVERIFIED. |
| Shipped Container exposes store; Hive/server composition | `test_goal_wiring.py:43,158` passes actual factory exposure and authorized end-to-end writes. Both shipped callers inspected: Hive `backend/adapters/maistro_core.py:195`, server `maistro_server/main.py:344`. Durable application startup/restart UNVERIFIED. |
| Durable Goal/revision/Run readback after restart | `test_goal_restart_readback.py:36` passes SQLite connection close/reopen. It does not restart Hive/server processes, and uses an in-memory Project fixture. PostgreSQL and deployed restart UNVERIFIED. |
| No competing GoalRun/OrchestratorRun/executor/Goal lifecycle | Convergence freeze PASS against supplied base. Lifecycle classification gate independently FAILS; not waived. |
| Preserve merged 056/057 identity/ancestry, append coordinated unused ID | Static installed-base tests exercise graph shape and historical byte equality; Goals are 061 after 060. Central coordination UNVERIFIED. |
| Populated actual c560d4c/4675101 installed-base upgrades without stamp rewrite/reset | Both live PostgreSQL-major legs skipped: UNVERIFIED. |
| Three Goal tables usable after each upgrade; facts/keys/Run data and planner artifacts survive; reopen provenance | PG17/PG18 UNVERIFIED. Existing durable-reopen migration test covers planner snapshot only, not both installed-base snapshots. |
| Fresh install, unique IDs/single head, downgrade/refusal/reapplication; quota ancestry and supported-history audit | Static migration tests/single-head command pass. PG17/PG18 live tests, full older-history compatibility and allocation coordination UNVERIFIED. |

Production tracing confirms `container.py:2362` calls `wire_goal_store`, line 2648
exposes it, and lines 274-284 wrap the Container's own Workspace authority.
`goals/wiring.py:61-65` refuses an incomplete PG schema without a fallback store.
`goals/authorization.py:144-162` makes absent/foreign Goals the same refusal.
These are reachable seams, but factory tests alone do not prove deployed restart.

## Handoff and limits

Only this report changed; no source/test/workflow/ledger/grant changes. No test
addition, so no inventory delta is required. The explicit vulture-ledger exception
does not justify amending an already matching ledger. Do not evade lifecycle
classification by changing its vocabulary: `scripts/ratchet_provenance.py:478-504`
requires an independently landed grant, and none is present in the supplied base.

The prior block remains unresolved. Next actions require an owner-authorized
trusted-base GoalStatus grant, exact-candidate failed integration producer logs,
and live PG17/PG18 infrastructure. This report makes no integration approval or
closure claim. The inherited unrelated diff remains unreviewed and untouched.

Progress: checked 1 assigned item; done 0 repairs; skipped 0 items; errors 2
confirmed blocker categories (lifecycle authorization, unavailable database
infrastructure); integration producer failure UNRESOLVED. Verdict: **BLOCKED**.
