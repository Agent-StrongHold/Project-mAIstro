# Issue #42 repair — c0edf658

## Scope and disposition

Assigned worktree `auto-42` started clean at
`5c26ee1ec10273129473dda59bb8d191ba1ca009`; assigned base
`a8258ee24dd957d0f0b302db4eee90661fe23439`. Frozen inputs: issue #42 and supplied
dispatch snapshot, prior result e64f9d82, and check-0 through check-6 logs.
No remote enumeration, GitHub mutation, merge, or dependency/ledger amendment.

**NEEDS-DEEP-REVIEW.** The named audit/vulture failures do not reproduce. This
round repairs a concrete acceptance-evidence gap rather than changing passing
dependencies or inventing scanner findings: the prior direct PostgreSQL
Invocation suite used a fake pool. Seven new tests now exercise the production
store and service against real PostgreSQL, including competing workers and
stale-write rejection. This does not establish the remaining parent-issue
acceptance criteria or authorize integration.

Read repository instructions and accepted ADRs a66b (lifecycle), 1f7c
(Runtime), f383/b36a (fencing and renewal/reclaim), 6b46 (Invocation), and 6201
(in-agent delegation). Reconciliation: b36a extends f383's initial non-reclaim
boundary; 6201 intentionally keeps in-agent delegation inside its existing
Attempt rather than inventing another NodeRun. No new execution, event,
authorization, scheduling, or Goal authority is introduced.

## Changed files

- `packages/maistro-core/tests/capabilities/test_pg_invocation_contention.py`:
  four claim-state cases, two physical-dispatch/replay cases, one revision-CAS
  case. Independent asyncpg pools use production JSON codecs and the migrated
  schema, not a fake or a schema/index created by this test.
- `docs/testing/inventory-notes/auto-42-live-invocation-contention.md`: +7 core
  tests. No shared inventory baseline edit.
- This report.

The service races rendezvous at provider resolution **after both services read
empty history**, then hold the winning physical call open until the losing
worker is refused. They cannot pass merely because one service's local lock or
an earlier completed-history read serialized admission. A fresh service reads
through the other connection pool, preserving the first dispatch's Invocation,
NodeRun and Attempt identifiers. COMPLETED replays; UNKNOWN refuses dispatch
before provider selection. These are Invocation contract tests, not fabricated
claims of a full persisted Run/NodeRun/Attempt/Event chain or a process restart.

## Fresh validation

Logs and temporary mutation plugin are in job directory
`/home/dev/maistro/jobs/c0edf658bbbe44aab733c0086e49fc27` under `worker-*` names.
All validation used long tool timeouts (600–900 seconds except the bounded
connection check). Python validation used `uv run`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,332 findings match 1,332 reviewed identities; zero unclassified. No ledger amendment warranted. |
| `npm audit --audit-level=high` in `packages/hive-conductor/frontend` | PASS: zero vulnerabilities. Reported source-map-js advisory does not reproduce. |
| Security workflow: `uv sync --locked --all-extras`; `uv pip install pip-audit`; `uv pip freeze --exclude-editable`; `uv run pip-audit --strict --format=json -r <frozen requirements>`; `uv run python scripts/pip_audit_gate.py <report>` | Raw audit exit 1, existing allowed ecdsa PYSEC-2026-1325 only (duplicate report rows); policy and direct-dependency usage gates PASS. Reported multidict/werkzeug findings do not reproduce. Restored `uv sync --locked --extra dev`. |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3,036 files |
| `uv run python scripts/check-execution-lifecycles.py` | PASS: 19 classified lifecycles |
| `uv run python scripts/check-foreign-harness-egress.py` | PASS |
| `uv run python scripts/check-wiring-reads.py` | PASS: 11 reviewed unread DI fields unchanged |
| `uv run pytest packages/maistro-core/tests/capabilities/test_pg_invocation_contention.py -x -q -rs` with live PG | **7 passed**, zero skips |
| Focused core command below with live PG | **2,155 passed, 3 skipped, 6 warnings** |
| `uv run pytest packages/hive-conductor/backend/tests/test_dag_run_cancel_route.py packages/hive-conductor/backend/tests/test_hyperlight_executor.py -x -q` | **13 passed** |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` in driver/default environment | PASS: 14,343 tests; +7 exactly |

Focused core command:

```sh
uv run pytest \
  packages/maistro-core/tests/runs \
  packages/maistro-core/tests/runtime \
  packages/maistro-core/tests/graph/durable_runs \
  packages/maistro-core/tests/capabilities/test_binding_invocation.py \
  packages/maistro-core/tests/capabilities/test_invocation_store.py \
  packages/maistro-core/tests/capabilities/test_pg_invocation_store.py \
  packages/maistro-core/tests/capabilities/test_pg_invocation_contention.py \
  packages/maistro-core/tests/integration/test_one_trace_end_to_end.py -x -q -rs
```

Database validation used the existing dedicated `auto42_387420` database,
revision `058`, after verifying its connection and logical-scope partial unique
index. No credentials were printed or committed. `DATABASE_URL` and
`MAISTRO_DATABASE_URL` were unset for tests; `MAISTRO_TEST_PG_DSN` selected the
shared test fixture. Docker was unavailable at `unix:///var/run/docker.sock`;
the already-running PostgreSQL remained reachable.

### Failure-sensitive evidence

An external, temporary pytest plugin changed only the behavior of the test
process; production files and database indexes were not edited:

- Mutating the stored effect scope back to physical NodeRun scope fails
  `test_database_claim_spans_physical_node_visits[created]`: **2 accepted,
  expected 1** (`worker-mutation-scope.log`, pytest exit 1).
- Replacing the caller's stale revision with the current revision before save
  fails `test_stale_worker_cannot_overwrite_a_terminal_fact`: **DID NOT RAISE
  StaleInvocationUpdate** (`worker-mutation-cas.log`, pytest exit 1).
- Normal focused tests ran subsequently without the plugin and passed.

### Non-passing commands and limitations

- Inventory run with PG DSN set collected 14,360 versus expected 14,343 (exit 1).
  Rerunning with the driver's default environment collected exactly 14,343 and
  passed. The +17 environment-dependent collection difference was **not**
  banked as a test addition or used to modify the baseline.
- `uv run pytest packages/maistro-server/tests/test_task_attempt_execution.py
  -x -q` exited 4: **file not found; skipped**. This was an unresolved-path
  validation mistake, not evidence of a failing production test. No server
  pytest evidence is claimed for this round.
- Three focused-suite skips are explicit backend limitations: archive payload
  movement on the memory backend, and separately readable continuation storage
  on two backends. Six existing SQLite worker-thread teardown warnings remain.
- Full multi-package CI `test` was not reproduced; passing focused commands and
  the reported audit step cannot be represented as the entire job passing.

## Acceptance matrix

| Issue criterion | Current executed evidence and residual limit |
| --- | --- |
| Every physical execution has an Attempt | Core execution/chat/durable-Graph suites pass. `runs/execution.py:395-413` persists leased Attempt before launch; `:594-600` submits the Attempt ID to Runtime. Universal coverage **UNVERIFIED**. |
| Retry creates chronological Attempts | Live three-backend execution/spine suites pass, including fresh IDs/ordinals, lease epochs, and stale-fence refusal. |
| Canonical retry/effect contract; ambiguous non-idempotent effects not blindly rerun | Durable ambiguous-effect regression and the new live PG contention/replay/CAS tests pass. The prior fake-pool-only **PG Invocation contention gap is closed**. |
| Cancellation/deadlines cross Runtime and stop/classify physical work | Runtime/execution suites plus 13 Hive physical-cleanup tests pass; `runs/execution.py:466-470` cancels and awaits its owned runtime task. |
| Chat durable lease/fence/reclaim and terminal-write recovery | Chat fault injection and shared live-PG lease conformance pass. **Active-chat PostgreSQL process-death/terminal-write recovery remains UNVERIFIED**: `test_chat_attempt_recovery.py:83` uses a default in-memory container. |
| No migrated-core physical bypass | Server's production TaskRunner receives `TaskAttemptExecutor` (`maistro_server/main.py:505-511`); Container admission and graph adapters inspected; bounded lifecycle/wiring/egress gates pass. `tasks/runner.py:278-288` still permits optional direct execution. Its compatibility composition's inclusion in the universal criterion is **UNRESOLVED**, not an asserted server bypass. |
| Run/NodeRun/Attempt/Invocation persistence and Events correlate over retry/recovery | Spine, trace, ambiguous-effect and fresh-store Invocation tests pass separately. **Combined persisted Invocation/Event crash/retry trace remains UNVERIFIED**; `test_one_trace_end_to_end.py:18` explicitly excludes Invocation. |
| #1169, #1170, #1194 close first | Exact issue objects in frozen dispatch each state closed (2026-09-13, 2026-09-10, 2026-09-29). No remote state changes. |

Next: a bounded active-chat PG crash/terminal-write recovery test and combined
persisted Invocation/Event retry trace, plus explicit compatibility-path scope
review. Do not repeat speculative dependency/ledger repairs against green gates.
Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 1, next: remaining acceptance evidence}`.
Writer output is a local commit/handoff only, never integration approval.
