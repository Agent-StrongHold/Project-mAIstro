# Issue #42 repair — e64f9d82

## Frozen scope

- Issue #42 only; branch `auto-42`, starting head
  `eb90eedb91720bc0657fc7a706769578de5af0a3`, base
  `a8258ee24dd957d0f0b302db4eee90661fe23439`.
- Assigned worktree `/home/dev/Git/wt/auto-42` was clean.
- Inputs: supplied dispatch-context.json, seven check logs, prior result
  b19a4b90a7c641c485c2ea459a1220c0. No remote enumeration or mutations.
- Repair targets: reported frontend npm audit and Python supply-chain failures;
  exact vulture gate; existing Attempt/ExecutionRuntime acceptance evidence.
- Candidate edit files frozen to this report, frontend package-lock.json and
  package.json, pyproject.toml/uv.lock, and quality/vulture-baseline.json only if
  the exact gate proves reviewed identity drift. Existing runtime and test files
  are inspection/validation targets, not speculative rewrite targets.
- Assumption: the current request is a writer CI-repair round. Historical review
  gaps must be checked, not silently treated as resolved. No develop sync is
  requested absent evidence of an actual conflict.

## Progress

- Confirmed starting HEAD and clean worktree; inspected instructions and prior
  result. Prior result reports successful audit gates but unresolved breadth of
  integration evidence; neither claim is accepted without current validation.
- Inspected all seven supplied check logs: sync/lint/format/inventories pass;
  pytest reports 684 passed, 124 skipped and six SQLite worker-thread warnings.
  Skips are not counted as acceptance evidence.
- Fresh exact vulture gate passes: 1,332 findings match 1,332 identities against
  the assigned base, no unclassified findings. No ledger change is justified.
- Read the complete primary issue body and all 41 comments from the frozen
  dispatch snapshot. Historical comments do not authorize closure or gate edits.
- Fresh Hive and Canvas `npm audit --audit-level=high`: both exit 0, zero
  vulnerabilities. Fresh supply-chain workflow (locked all-extras sync,
  pip-audit install, freeze, strict JSON audit, pip_audit_gate.py): raw audit
  exit 1 for existing allowed ecdsa PYSEC-2026-1325 only; policy gate exit 0,
  direct-dependency usage passes. Reports saved as
  `/tmp/auto-42-e64f9d82-{deps.txt,pip-audit.json}`. Neither reported multidict
  nor werkzeug finding reproduces. No dependency or allowlist edit warranted.
- Accepted runtime/fencing ADRs require persisted Attempt authority before
  Runtime launch. Current `runs/execution.py:395-403,594-600` does that; Runtime
  consumes the Attempt ID, not the Run ID. Cancellation awaits its owned task
  (`:466-470`). No competing execution authority is introduced in this round.
- Fresh `uv run ruff check .` and `uv run ruff format --check .` pass. After
  restoring the locked dev environment, focused core runs/runtime/durable-Graph,
  binding/Invocation stores, and one-trace suites: **1,856 passed, 295 skipped,
  six warnings** (`/tmp/auto-42-e64f9d82-focused.log`). PostgreSQL is not configured
  for that run, so its skipped cases do not establish durable acceptance.
- Inspected tests: the ambiguous-effect test drives the real durable executor
  and asserts one dispatch across three logical visits plus retained original
  Invocation identity. The direct PG Invocation suite instead uses a fake pool
  (`test_pg_invocation_store.py:5`). Chat recovery injects renewal/terminal-write
  failures into a default in-memory container (`test_chat_attempt_recovery.py:83`).
  One-trace asserts Event/Attempt joins but explicitly omits Invocation (`:18`).
  Those tests are meaningful but do not prove a combined durable crash trace.
- Production server supplies `TaskAttemptExecutor` (`maistro_server/main.py:511`)
  and Container refuses unadmitted chat (`container.py:806-808`). The library
  `TaskRunner._execute_work` nevertheless allows a direct executor when the Run
  or adapter is absent (`tasks/runner.py:278-288`). Reachability/classification of
  that compatibility composition is unresolved, not an asserted server bypass.
- Fresh execution-lifecycles, foreign-harness-egress and wiring-reads gates pass;
  they classify 19 lifecycles and retain 11 reviewed unread DI fields. These
  bounded gates are not exhaustive physical-execution coverage.
- Frozen dispatch issue objects independently confirm #1169, #1170 and #1194
  closed (2026-09-13, 2026-09-10 and 2026-09-29 respectively).
- Docker availability check failed: cannot connect to
  `unix:///var/run/docker.sock`. Existing local test-DSN files are available;
  validated the previous dedicated database before attempting live tests.
- Existing DSN connects to dedicated `auto42_387420`, schema revision `058`.
  No migration or credentials change was needed. The same focused command with
  `MAISTRO_TEST_PG_DSN` set (application database variables unset, auth off and
  dry-run enabled) gives **2,148 passed, 3 skipped, six warnings** in 125 seconds.
  Log: `/tmp/auto-42-e64f9d82-focused-pg.log`. This supersedes the non-PG count;
  do not sum them. Remaining skips are intentional backend-capability cases.
  Live Run-store conformance passed; configuring PG does not convert the fake
  Invocation pool or default in-memory chat fixture into live-PG tests.
- Fresh server task restart E2E with application `DATABASE_URL` set to that
  validated dedicated database: **1 passed** (`/tmp/auto-42-e64f9d82-restart.log`).
  Its SIGKILL occurs before queued task dispatch (`test_task_restart_recovery.py:29`),
  not during an active chat turn; it cannot close the chat process-death gap.
- Hive cancellation/Hyperlight suites: **13 passed**. Core inventory: **14,336**,
  matching the existing baseline. `git diff --check` passes. No test additions or
  count changes, so no inventory-delta note or baseline amendment is needed.

## Executed validation commands

All Python commands used `uv run`; validations used 600-second tool timeouts
(except the bounded 15-second PostgreSQL connection check).

```sh
uv sync --locked --extra dev
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
# In each of packages/hive-conductor/frontend and packages/maistro-canvas/frontend:
npm audit --audit-level=high
uv sync --locked --all-extras
uv pip install pip-audit
uv pip freeze --exclude-editable > /tmp/auto-42-e64f9d82-deps.txt
uv run pip-audit --strict --format=json -r /tmp/auto-42-e64f9d82-deps.txt > /tmp/auto-42-e64f9d82-pip-audit.json
uv run python scripts/pip_audit_gate.py /tmp/auto-42-e64f9d82-pip-audit.json
uv sync --locked --extra dev
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-execution-lifecycles.py
uv run python scripts/check-foreign-harness-egress.py
uv run python scripts/check-wiring-reads.py
# Executed first without PG, then with the validated dedicated test DSN:
uv run pytest packages/maistro-core/tests/runs packages/maistro-core/tests/runtime packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/capabilities/test_binding_invocation.py packages/maistro-core/tests/capabilities/test_invocation_store.py packages/maistro-core/tests/capabilities/test_pg_invocation_store.py packages/maistro-core/tests/integration/test_one_trace_end_to_end.py -x -q -rs
uv run pytest packages/maistro-server/tests/test_task_restart_recovery.py -x -q -rs
uv run pytest packages/hive-conductor/backend/tests/test_dag_run_cancel_route.py packages/hive-conductor/backend/tests/test_hyperlight_executor.py -x -q
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
git diff --check
```

## Acceptance and disposition

| Criterion | Executed evidence; limitation |
| --- | --- |
| Every physical execution has an Attempt | Execution/chat/durable-Graph suites passed; production persistence-before-launch inspected. Universal coverage **UNVERIFIED**: optional TaskRunner direct-executor composition remains unclassified in this review. |
| Retry creates a chronological Attempt | Execution and three-backend spine suites passed, including ordinals/new identity and stale-fence rejection. |
| Canonical retry/effect contract refuses ambiguous non-idempotent redispatch | Ambiguous-effect regression passed: three visits, one dispatch, original UNKNOWN Invocation retained. Real PG Invocation concurrency **UNVERIFIED** by the inspected direct suite. |
| Cancellation/deadlines stop physical work or classify non-abortable work | Runtime/execution suites and 13 Hive cancellation/Hyperlight tests passed; cancellation awaits owned runtime task. |
| Chat durable lease/fence/reclaim and terminal-write repair | Chat fault-injection tests and live shared-store lease conformance passed. Chat process-death plus PostgreSQL terminal-write recovery **UNVERIFIED**, not proved by the queued-task restart E2E. |
| No migrated-core physical bypass | Server, Container and durable-Graph wiring inspected; bounded lifecycle/wiring/egress gates passed. Exhaustive compatibility-path classification **UNVERIFIED**. |
| Run/NodeRun/Attempt/Invocation and Events correlate over retry/recovery | Execution, ambiguous-effect, one-trace and task restart suites passed. Combined persisted Event/Invocation crash/retry trace **UNVERIFIED**; separate suites cannot be represented as that trace. |
| #1169/#1170/#1194 close first | All three frozen dispatch objects explicitly say closed; no remote state mutation. |

**NEEDS-DEEP-REVIEW.** Named CI-gate triage is complete and none of the named
failures reproduces. The previous acceptance-review block is not resolved by
these passing gates. No evidence-backed dependency, runtime or ledger repair was
identified within the frozen repair targets; speculative edits would be cosmetic
or would misrepresent the evidence. Accepted ADR b36a extends f383 with renewal
and reclaim, while a66b/1f7c preserve the canonical hierarchy; no architectural
reconciliation or new authority was needed.

Only changed file in this round: `docs/testing/issue-42-e64f9d82-repair.md`.
All incoming committed work is preserved. No grants, ledgers, lockfiles, code,
tests or gate policy were changed. Full multi-package CI `test` was not rerun.
Six existing SQLite worker-thread teardown warnings remain a residual risk.
Docker daemon was unavailable, but the already-running dedicated PostgreSQL was
reachable and used successfully. No credentials were printed or committed.

Next action is a bounded acceptance-evidence assignment for real PostgreSQL
Invocation concurrency, combined persisted Invocation/Event retry correlation,
and active-chat process-death/terminal-write recovery, plus a scope decision on
the optional TaskRunner compatibility path. Do not repeat speculative dependency
or ledger repairs against passing scans.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: acceptance evidence}`.
This report is committed locally as the writer handoff, not integration approval;
no push, PR, merge, issue comment or closure was performed.
