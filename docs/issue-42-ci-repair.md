# Issue #42 CI repair checkpoint

Snapshot: issue #42 only, branch `auto-42`, starting HEAD
`8570d430f00133f49649eca57af2dec977cb1d7d`, supplied base
`7334621bf797178dd992622d55aaead33bf9d094`. Initial worktree clean.

Repair scope: demonstrated npm source-map-js audit failure, Python multidict /
werkzeug audit findings, and the explicitly requested exact vulture gate.
Candidate repair files are `packages/hive-conductor/frontend/package-lock.json`,
`uv.lock`, and (only if demonstrated necessary) `quality/vulture-baseline.json`;
this report records validation. Existing integration code/tests are inspection
and validation scope, not a new implementation campaign.

Supplied driver logs: dependency sync, ruff lint/format and three package
inventory checks passed; targeted execution tests report 607 passed, 124 skipped
with SQLite thread teardown warnings. These are supplied evidence, not newly
executed validation. Previous verifier blocked on dependency audits.

Assumption: the explicit Writer repair assignment governs (not the generic
Verifier no-edit text). No scheduler, execution authority, or security policy
changes are intended. Issue closure is never part of this round.

## Initial executed checks

- Exact requested vulture scan passed: 1,336 findings, all reviewed; no ledger
  amendment is justified or necessary.
- Hive npm audit reproduced source-map-js GHSA-68fv-2mgg-jv7q (high).
- The named CI `test` job actually audits **Canvas**, not Hive
  (`.github/workflows/ci.yml:593`). Running that exact gate reproduced the same
  source-map-js finding plus proxy-addr GHSA-jqcg-44mw-7w3h (critical).
  Scope reconciliation: add `packages/maistro-canvas/frontend/package-lock.json`
  to the frozen repair files to fix this demonstrated failure of the assigned
  gate; no other dependency trees will be searched or changed.
- Installed multidict is 6.7.1 and werkzeug is 3.1.8. pip-audit is not installed;
  install the CI tool before evaluating the Python gate.
- Read accepted Runtime, lifecycle, and lease ADRs (1f7c, a66b, f383).
  Runtime mechanics remain subordinate to canonical Attempt identity; this
  dependency-only repair does not change their contracts.
- Supplied snapshot marks #1169, #1170 and #1194 closed (respectively
  2026-09-13, 2026-09-10 and 2026-09-29). No live issue-state claims are made.

## Repair applied

The strict Python audit reproduced exactly the two untriaged CVEs supplied by
review: multidict CVE-2026-104874 and werkzeug CVE-2026-102598. Updated only those
locked packages to the audit's fixed versions (6.9.1 and 3.1.9). Targeted npm
updates moved source-map-js to 1.2.2 in both frontends and proxy-addr to 2.0.8 in
Canvas. No manifest bounds, allowlists, gates, or quality ledgers changed.

Commands: `npm --prefix <frontend> update source-map-js [proxy-addr]
--package-lock-only --ignore-scripts`; `uv lock --upgrade-package
multidict==6.9.1 --upgrade-package werkzeug==3.1.9`.

## Executed post-repair dependency validation

- Hive: `npm ci && npm run lint && npm run build && npm audit
  --audit-level=high` passed; zero vulnerabilities, 94 existing lint warnings
  within the unchanged 96-warning ceiling. npm 9.2 reports an engine warning
  for Redocly's >=9.5 npm requirement; installation and build succeed.
- Canvas: `npm ci && npm run test:ci && npm run lint && npm run build && npm
  audit --audit-level=high` passed; 79 tests, zero vulnerabilities, 13 existing
  lint warnings at the unchanged ceiling, advisory bundle-size warning.
- `uv sync --locked --all-extras`; install pip-audit; `uv pip freeze
  --exclude-editable`; `uv run pip-audit --strict --format=json -r <freeze>`;
  `uv run python scripts/pip_audit_gate.py <report>`: gate passed. Raw audit
  still exits 1 for the existing, already-triaged ecdsa advisory; no new
  exceptions were added. Reports: `/tmp/auto-42-audit-{before,after}.json`.
- `uv run ruff check .`: passed (including direct-dependency usage gate).
- `uv run ruff format --check .`: 2,999 files already formatted.

Inspection correction: guessed server `services/run_execution.py` and Hive
`services/chat_execution.py` do not exist (not found; skipped). The resolved
production implementations are core `runs/execution.py` and
`runs/chat_execution.py`. The former creates a leased Attempt before launching
Runtime and passes `attempt.attempt_id` as its execution ID (lines 395, 591).

## Execution acceptance revalidation checkpoint

- `uv run pytest packages/maistro-core/tests/runs
  packages/maistro-core/tests/runtime packages/maistro-core/tests/graph/durable_runs
  packages/maistro-core/tests/capabilities/test_invocation_store.py -x -q`:
  **1,808 passed, 295 skipped**, six existing SQLite thread teardown warnings.
  Full output: `/tmp/auto-42-core-tests.log`.
- `uv run pytest packages/maistro-server/tests/test_task_restart_recovery.py
  packages/maistro-canvas/tests/test_publishing.py -x -q`: **27 passed, 1 skipped**.
  The skipped server test requires a migrated live PostgreSQL database.
- `uv run python scripts/check-execution-lifecycles.py`: passed, 19 classified
  vocabularies, no unauthorized competing lifecycle.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps ...`: FAILED, cannot connect
  to Docker daemon. Live PostgreSQL/restart acceptance remains UNVERIFIED in
  this repair round; historical notes do not substitute for executing it.

- `uv run pytest packages/hive-conductor/backend/tests/test_dag_run_cancel_route.py
  packages/hive-conductor/backend/tests/test_hyperlight_executor.py -x -q`:
  **13 passed**, including a real mid-flight provider unwinding through the
  shipped cancel handler and subprocess timeout/cleanup behavior.
- `uv run pytest packages/maistro-core/tests/integration/test_one_trace_end_to_end.py
  packages/maistro-core/tests/capabilities/test_pg_invocation_store.py
  packages/maistro-core/tests/a2a/test_delegate.py
  packages/maistro-core/tests/graph/nodes/test_agent_spawn_harness.py -x -q`:
  **99 passed**. The pg Invocation tests use a pool double; this does NOT
  substitute for the skipped live database/restart test.
- `check-suite-inventory.py --suite packages/maistro-core/tests`: passed,
  13,952 node IDs; same command for server: passed, 524 node IDs.
  No tests were added, removed, or changed in this dependency repair; no
  inventory delta is needed. Existing behavioral suites were executed rather
  than adding tests that merely assert dependency version strings.
- Parsed lockfile comparison against starting HEAD confirms exactly two Python
  package entries changed (multidict, werkzeug), one Hive npm entry
  (source-map-js), and two Canvas entries (source-map-js, proxy-addr).
  `git diff --check`: passed.

## Acceptance disposition (not an integration approval)

| #42 criterion | Fresh evidence / remaining limit |
| --- | --- |
| Every physical execution has an Attempt | Core `runs/test_execution.py::test_attempt_id_is_runtime_execution_id_and_reconciles_after_terminal_persist` passed; production `runs/execution.py:395,591` persists then launches with that ID. Chat/durable Graph suites passed. Universal coverage of every production path is **UNVERIFIED** by this focused repair. |
| Retry creates chronological Attempts | `runs/test_execution.py::test_failed_attempt_can_retry_same_logical_node_run` and correlation retry tests passed; old Attempt preserved, new ID for retry. |
| One effect contract; ambiguous effects not blindly replayed | `graph/durable_runs/test_ambiguous_effect_replay_guard.py` passed: actual durable executor/Invocation service dispatches once across three visits, records UNKNOWN under original IDs. Invocation-store tests passed (SQLite plus pool-double pg); live PG concurrency remains **UNVERIFIED**. |
| Cancellation/deadlines stop work or classify truthfully | Runtime/run suites, shipped Conductor cancellation-handler tests and subprocess cleanup tests passed. Provider finally blocks and durable cancelled state asserted, not merely status mocks. This does not certify every external provider's abort capability. |
| Chat lease/fence/reclaim and terminal-write repair | All `runs/test_chat_attempt_recovery.py` cases passed through Container/ChatAttemptExecutor, including stopped heartbeat, stale fence, retry and store-failure recovery. Live PG crash/restart remains **UNVERIFIED**. |
| No bypass on migrated core paths | Inspected core Attempt and chat adapters and durable Graph firewall; A2A and harness tests passed. Lifecycle gate passed but only scans lifecycle vocabulary, not physical-call reachability. Exhaustive production bypass absence is **UNVERIFIED** in this repair round. |
| Persistence and Events correlated across retry/recovery | `runs/test_execution_is_correlated.py`, `integration/test_one_trace_end_to_end.py`, spine conformance and ambiguous-effect tests passed, covering canonical IDs and SQLite Event persistence. Live PG restart E2E skipped; cross-process coverage **UNVERIFIED** here. |
| #1169/#1170/#1194 close first | All three are closed in the supplied dispatch snapshot. No GitHub mutation or live re-enumeration performed. |

## Handoff

The assigned npm and Python audit failures are repaired and the exact requested
vulture scan needs no amendment. Focused validation totals **1,947 Python tests
passed, 296 skipped**, plus **79 frontend tests passed**. Test skips and SQLite
teardown warnings are not hidden. Accepted ADR b36a supplies reclamation semantics
beyond f383's original narrower lease boundary; no architecture changes were made.

Residual blocker for full issue acceptance: no reachable Docker daemon/live
PostgreSQL for the production restart/concurrency legs. An independent complete
production bypass review was not performed; the lifecycle scan is not equivalent.
The entire CI `test` job was not rerun; its demonstrated failing npm audit and
relevant frontend build/test steps were. Do not interpret this repair as issue
closure or integration approval.

Progress: checked 1 issue, repaired 1 assigned CI item, skipped 0 assigned items;
validation environment error 1 (Docker unavailable). Next: independent verification
with migrated PostgreSQL and complete production-path acceptance review.

