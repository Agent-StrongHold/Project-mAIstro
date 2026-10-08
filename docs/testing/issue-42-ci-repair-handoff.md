# Issue #42 CI repair checkpoint

## Frozen scope

- Sole issue: #42; sole worktree `/home/dev/Git/wt/auto-42`, branch `auto-42`.
- Starting HEAD `a0443a7a92f6801ee8dd75623c43fe17280cc67e`; supplied base `a8258ee24dd957d0f0b302db4eee90661fe23439`.
- Repair targets: reported frontend source-map-js audit failure, Python multidict/werkzeug supply-chain findings, and exact-identity vulture gate if reproduced. Candidate edit files: `packages/hive-conductor/frontend/package-lock.json`, its `package.json` only if needed, `uv.lock`, dependency manifests only if required, `quality/vulture-baseline.json` only for reproduced reviewed debt, and this report. No execution architecture changes without concrete evidence.
- Validation scope: supplied driver logs, relevant accepted runtime ADRs and production wiring, existing focused runtime/recovery/replay tests, CI audit commands and vulture command. No new issue/PR enumeration or GitHub mutations.
- Assumption: this is a writer CI-repair round, not authorization to implement unrelated outstanding architecture work. Prior NEEDS-DEEP-REVIEW is an evidence gap to reassess, not permission to claim exhaustive verification.

## Initial evidence

- Starting tree clean and HEAD matches assignment.
- Driver check-0 through check-6 inspected: dependency sync, Ruff checks, scoped tests (684 passed / 124 skipped), and three inventory gates passed. Driver pytest includes SQLite worker-thread warnings; skipped cases are not acceptance proof.
- Prior result explicitly leaves universal physical execution coverage, PostgreSQL Invocation concurrency, PostgreSQL chat crash recovery and combined recovery correlation unverified. This round must not silently convert those into a pass.

## Progress

Reproduced named gates on the assigned HEAD:

- Exact requested vulture scan passed: 1,332 findings match 1,332 reviewed identities, zero unclassified. No ledger amendment justified.
- Hive `npm audit --audit-level=high` passed with zero vulnerabilities. The actual lockfile already has source-map-js **1.2.2** at line 3376, not the reported 1.2.1.
- CI supply-chain sequence (`uv sync --locked --all-extras`, `uv pip install pip-audit`, `uv pip freeze --exclude-editable`, strict JSON pip-audit, then `scripts/pip_audit_gate.py`) passed the gate. Raw audit exit 1 reports only two duplicate occurrences of existing allowed ecdsa PYSEC-2026-1325; no multidict/werkzeug finding. Direct-dependency usage check also passed. Report: `/tmp/auto-42-pip-audit.json`; frozen environment: `/tmp/auto-42-deps.txt`.
- No dependency or gate-policy edits are supported by current evidence. Remaining work is focused acceptance validation and honest handoff, not speculative repair.

Additional checks passed: full-tree `uv run ruff check .`, `uv run ruff format --check .` (3,035 files), execution-lifecycles (19 classified), foreign-harness-egress, wiring-reads (11 existing reviewed unread fields), and Canvas `npm audit --audit-level=high` (zero vulnerabilities). No gate weakened.

Read accepted ADRs 1f7c, a66b, f383 and b36a: Runtime consumes Attempt identity; Run persistence owns leases/fences; b36a extends the original fencing-only boundary with renewal/reclaim. No architectural reconciliation change is needed in a documentation-only repair checkpoint.

Inspection confirms `runs/execution.py:395` persists the leased Attempt before `:594` launches Runtime with its ID; chat uses this service with default TTL (`runs/chat_execution.py:212-224`). `tasks/runner.py:286-287` still exposes the optional direct-executor compatibility path. Its existence does not establish a bypass in configured server wiring, but universal library coverage cannot be claimed. The direct PG Invocation test's fake pool is documented at `tests/capabilities/test_pg_invocation_store.py:5`.

An attempted read of `tests/runs/test_chat_recovery.py` returned not found; skipped that guessed path and resolved the actual existing `test_chat_attempt_recovery.py` from the directory listing before validation.

Focused tests without PostgreSQL: **1,853 passed, 295 skipped, 6 warnings** in 47.96s. Command: `uv run pytest packages/maistro-core/tests/runs packages/maistro-core/tests/runtime packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/capabilities/test_binding_invocation.py packages/maistro-core/tests/capabilities/test_invocation_store.py packages/maistro-core/tests/capabilities/test_pg_invocation_store.py -x -q -rs`. Log: `/tmp/auto-42-focused-tests.log`. SQLite worker-thread teardown warnings remain. Hive `test_dag_run_cancel_route.py` and `test_hyperlight_executor.py`: **13 passed**.

Attempted PostgreSQL validation using the prior round's existing credential file (never printed). Connection confirms dedicated database `auto42_387420`, but querying `alembic_version` failed with `UndefinedTableError`; tests did not run against an unvalidated schema. This matches the prior report's warning that migration tests downgrade their isolated database. Will migrate that dedicated test database before retrying. The optional graph-local conftest read was not found; the actual shared PostgreSQL fixture is `packages/maistro-core/tests/conftest.py:164`, and truncates this test database between cases.

PostgreSQL setup repaired with `DATABASE_URL=<validated dedicated DSN> uv run alembic upgrade head`: passed through revision 058 (`/tmp/auto-42-migrate.log`). Re-ran the same focused command with `MAISTRO_TEST_PG_DSN`, `REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`, and both application database variables unset: **2,145 passed, 3 skipped, 6 warnings** in 109.91s (`/tmp/auto-42-focused-pg-tests.log`). The three skips are explicit backend capability cases (archive movement / separately readable continuation store), not missing PostgreSQL. This supersedes, rather than adds to, the earlier 1,853-case passing count.

Additional executed acceptance checks:

- With the dedicated PostgreSQL application URL configured: `uv run pytest packages/maistro-server/tests/test_task_restart_recovery.py -x -q -rs`: **1 passed**, no skip (`/tmp/auto-42-restart-tests.log`). This kills a process with a queued task and proves recovery/execution/projection on restart; it does **not** kill an active chat Attempt.
- `uv run pytest packages/maistro-core/tests/integration/test_one_trace_end_to_end.py -x -q`: **3 passed**. Its Invocation omission is explicit at lines 18–21; the historical explanation there is not adopted as current production truth.
- Core inventory run while the PostgreSQL/all-extras environment remained active failed: expected 14,336, collected 14,353. After restoring the driver's exact dependency/environment shape (`uv sync --locked --extra dev`, unset `MAISTRO_TEST_PG_DSN`, `DATABASE_URL`, `MAISTRO_TEST_DATABASE_URL`), the same inventory command passed at **14,336**. No test source changed; no inventory delta was invented to bank environment-dependent collection.
- `git diff --check`: passed. Driver server/canvas inventory checks also passed; no suite changes in this round.

## Acceptance matrix

| #42 acceptance criterion | Fresh evidence and limit |
| --- | --- |
| Every physical execution has an Attempt | Leased persistence precedes runtime launch (`runs/execution.py:395,594`); execution, chat and durable-Graph suites pass. Universal library composition remains **UNVERIFIED** because `tasks/runner.py:286-287` permits an optional direct executor. |
| Retry creates a chronological Attempt | Execution/fencing suites and live three-backend spine conformance passed. New IDs, ordinals and lease epochs are asserted rather than rewriting history. |
| One replay/effect contract; ambiguous effects are not blindly redispatched | Durable-Graph ambiguous-effect guard passed, asserting three chronological visits but only one dispatch and one UNKNOWN Invocation retaining the original Attempt. Invocation store suites passed; real PostgreSQL Invocation concurrency remains **UNVERIFIED**, since its direct suite uses a fake pool. |
| Cancellation/deadlines cross Runtime and stop/classify physical work | Runtime/execution suites and 13 Hive cancellation/Hyperlight tests passed, including physical cleanup. `runs/execution.py:466-470` cancels and awaits the owned runtime task. |
| Chat leases/fences/reclaim and terminal-write recovery | Container wiring and `test_chat_attempt_recovery.py` passed (TTL, renewal failure, stale fence, terminal-write repair); live shared Run-store lease cases passed. PostgreSQL chat process-death recovery remains **UNVERIFIED**; the chat fixture at lines 83–84 uses its default in-memory container and the process-kill test is tasks. |
| No migrated-core physical bypass | Server supplies `TaskAttemptExecutor` (`maistro_server/main.py:511`); Container refuses chat without a canonical Run (`container.py:806-808`); durable Graph uses Attempt execution. Three bounded wiring/lifecycle/egress gates passed. Exhaustive classification of optional compatibility compositions remains **UNVERIFIED**. |
| Persistence, Invocation and Events correlate through retries/recovery | Execution-correlation, recovery, live spine, ambiguous-effect and one-trace suites passed; task restart E2E passed. Combined PostgreSQL Event+Invocation crash/retry trace remains **UNVERIFIED**; separate passing suites are not that proof. |
| #1169/#1170/#1194 close first | Independently read their objects in the supplied frozen dispatch JSON: all `state: closed`; closure dates September 13, September 10, September 29, 2026 respectively. No GitHub mutations. |

## Final disposition

**NEEDS-DEEP-REVIEW**, not integration approval. All specifically named current audit/vulture failures fail to reproduce, so no source, lockfile, ledger or grant amendment is warranted. The prior acceptance-review block is **not resolved** by re-running fake-pool/in-memory tests; focused live validation strengthens Run-store evidence but does not close the distinct gaps above. Full multi-package CI `test` job was not run locally.

Only changed file: `docs/testing/issue-42-ci-repair-handoff.md` (this evidence/handoff). No new tests, therefore no test inventory delta note is required. Existing source/tests and all prior commits remain preserved. Six SQLite worker-thread teardown warnings remain an explicit residual risk, not hidden passes. The test database remains migrated to 058; no credentials were printed or committed.

Next: a bounded acceptance-testing assignment for actual PostgreSQL Invocation concurrency, combined Event/Invocation retry correlation, and chat process-death/terminal-write recovery; resolve the intended scope of the optional task compatibility path before asserting universal coverage. Do not repeat dependency or ledger edits against these already-passing gates.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: acceptance-review gaps above}`. Named CI-gate triage is complete; full issue readiness remains unresolved. This checkpoint is committed locally; no push, PR, issue mutation or protected-branch integration.
