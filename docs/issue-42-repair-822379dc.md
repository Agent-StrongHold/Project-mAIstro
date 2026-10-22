# Issue 42 repair — job 822379dc

## Frozen scope

- Only issue #42, branch `auto-42`, starting clean HEAD
  `bb7f638b0c40c712f43089c0984f434ba49c04b4`, base
  `626683154ce9dbd521e6754cee494190c0fb29f0` (both resolved locally).
- Process the supplied CI test/audit failure and exact vulture gate, then check
  the eight acceptance criteria from the captured dispatch context. No remote
  mutations or new issue/PR enumeration.
- Candidate repair files: `packages/hive-conductor/frontend/package-lock.json`,
  `uv.lock`, `quality/vulture-baseline.json` (explicit repair exception only),
  and this report. Runtime source/tests are inspection-only unless actual new
  failure evidence requires an explicitly recorded scope amendment.
- No starting uncommitted changes; no salvage operation required.

## Initial evidence

Driver check-0 through check-6 logs were inspected: dependency sync, Ruff lint
and formatting, scoped tests (607 passed, 124 skipped, three aiosqlite thread
warnings), and all three inventory gates passed. These are not proof of live
PostgreSQL behavior or all issue acceptance criteria.

The prior result reported repaired audits but a blocked environment. This round
will rerun audits rather than presume either result. Initial workflow search
found `npm audit --audit-level=high` in ci.yml; a guessed supply-chain workflow
glob did not resolve, so that glob was skipped (no command executed against it).

Ambiguity: the lane is a writer repair, not read-only verifier. Proceed with
focused validation and an evidence-only commit if no reported defect reproduces.

## Results

- Fresh `uv sync --locked --extra dev`: passed.
- Exact assigned vulture command: passed, 1,332 findings / reviewed identities,
  zero unclassified. No ledger amendment justified by the actual scan.
- Both Hive and Canvas frontend `npm audit --audit-level=high`: passed, zero
  vulnerabilities. The CI `test` job audits Canvas; Hive was also checked to
  address the supplied finding. No lockfile mutation justified.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps`: cannot connect to daemon.
  The socket exists but is not a usable PostgreSQL service. Check local database
  availability once before treating live persistence verification as blocked.
  Result: local PostgreSQL 18 `main` is online on port 5432 with pgvector
  installed. Use a newly created, job-specific database; do not modify a shared
  existing database. This resolves the earlier assumption that Docker failure
  necessarily blocks live validation.
- Read accepted ADRs 1f7c, a66b and f383: persist Attempt before Runtime launch;
  Runtime ID equals Attempt ID; Run store owns leases/fences. No new execution
  authority or policy changes are warranted. Accepted b36a extends f383 with
  heartbeat/reclaim (liveness, not process restart, authorizes reclaim).
- CI-exact all-extras Python audit: `uv sync --locked --all-extras`,
  `uv pip install pip-audit`, freeze non-editables, strict JSON pip-audit:
  raw exit 1 for two report occurrences of existing ecdsa PYSEC-2026-1325.
  `scripts/pip_audit_gate.py` passed, including direct dependency usage.
  No multidict/werkzeug findings or audit policy changes.
- Local PostgreSQL peer login as `dev` failed (role absent); administrator
  access via `sudo -n -u postgres psql` succeeded. Will create dedicated role
  and database `auto42_822379dc` rather than alter existing roles/databases.
- `jq` is not installed; skip that extraction tool. The guessed
  `runs/task_execution.py` path was not found and is skipped; resolve the real
  task adapter by source search before inspecting it.
- Created dedicated PostgreSQL role/database `auto42_822379dc`; local-only
  credentials are in a mode-0600 `/tmp/auto-42-822379dc-pg.env`, not the tree.
  `uv run alembic upgrade head` passed (log `/tmp/auto-42-822379dc-migration.log`).
- Live PostgreSQL-enabled focused suite: **2,095 passed, 3 skipped, 6 warnings**
  in 112 seconds. Command: `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests/runs packages/maistro-core/tests/runtime
  packages/maistro-core/tests/graph/durable_runs
  packages/maistro-core/tests/capabilities/test_pg_invocation_store.py
  packages/maistro-core/tests/integration/test_one_trace_end_to_end.py -x -q`,
  with `MAISTRO_TEST_PG_DSN` set and `DATABASE_URL` unset to preserve ordinary
  fixture defaults. Log `/tmp/auto-42-822379dc-runtime.log`. Existing SQLite
  teardown thread warnings remain; not treated as PostgreSQL failures.
- Live PostgreSQL server restart E2E: `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1
  uv run pytest packages/maistro-server/tests/test_task_restart_recovery.py
  -x -q -rs` with both database variables configured: **1 passed**, not skipped.
  Log `/tmp/auto-42-822379dc-restart.log`. Real HTTP admission, SIGKILL, restarted
  lifespan recovery and third-process durable projection were exercised.
- `check-execution-lifecycles.py`, `check-foreign-harness-egress.py`, and
  `check-wiring-reads.py`: passed (19 lifecycles, 11 reviewed unread fields).
  These gates are bounded evidence, not universal reachability proofs.
- Hive cancel-route / Hyperlight cleanup suites: **13 passed**. Fresh root
  Ruff lint and formatting checks passed (3,007 Python files).
- Supplied snapshot confirms #1169, #1170, #1194 closed on September 13, 10,
  and 29 respectively. No remote re-enumeration.
- Inspection found `test_pg_invocation_store.py` deliberately uses a fake pool;
  its passing tests must not be described as live PostgreSQL Invocation proof.
  Validate the existing real migration/conformance coverage separately.
- `tasks/runner.py:284` retains an unfenced compatibility execution fallback
  when no Attempt adapter or Run ID exists. Production server wiring supplies
  `TaskAttemptExecutor` (`main.py:511`); universal absence of bypass must not be
  inferred from the Runtime-constructor search alone.
- With `MAISTRO_TEST_DATABASE_URL` pointing only at the job-specific database,
  `uv run pytest tests/migrations/test_capability_invocation_effect_index_migration.py
  tests/migrations/test_migration_chain.py
  packages/maistro-core/tests/capabilities/test_issue55_hardening.py -x -q -rs`:
  **18 passed**. Log `/tmp/auto-42-822379dc-pg-effects.log`. The migration suite
  resets its database intentionally; it checks real deployment schema and
  round-trip/adoption, not concurrent production Invocation dispatch.

## Acceptance disposition

| Criterion | Fresh executed evidence and limits |
| --- | --- |
| Every physical execution has an Attempt | Inspected `runs/execution.py:395` persist-before-launch and `:591` Runtime ID = Attempt ID; task/chat/Graph suites execute those services. Universal production coverage **UNVERIFIED**, particularly callers of the compatibility fallback in `tasks/runner.py:278-288`. |
| Retries create chronological Attempts | Passed `runs/test_execution.py`, `test_execution_is_correlated.py:76`, chat recovery and live three-backend spine conformance: stable logical Run/NodeRun, fresh Attempt ID/ordinal/fence. |
| One canonical replay/effect contract; no blind ambiguous redispatch | Passed `graph/durable_runs/test_ambiguous_effect_replay_guard.py:147`: actual durable Graph traversal and Invocation service, one dispatch over three visits, two refusals, original Invocation correlation. Live Run effect-claim conformance passed. Concurrent production **PostgreSQL Invocation** claims remain **UNVERIFIED**: `test_pg_invocation_store.py:5` declares its fake pool; live migration tests establish schema only. |
| Cancellation/deadline crosses Runtime; work stops or is classified | Runtime/runs/durable Graph tests passed, plus 13 Hive cancellation/process-cleanup tests. `runs/execution.py:466-470` cancels and awaits runtime work on failure; Hive tests observe provider unwinding/process reaping rather than status alone. No external-provider-wide abortability certification claimed. |
| Chat leases/fencing/reclaim and terminal-write recovery | Passed `test_chat_attempt_recovery.py`, inspected `chat_execution.py:212-224` TTL -> canonical RunExecutionService wiring, and live PostgreSQL shared lease/reclaim/fence conformance passed. Chat tests use in-memory Container and injected write/renewal failures; an actual PostgreSQL chat process crash and terminal-write recovery remains **UNVERIFIED** (the passing server SIGKILL test is tasks, not chat). |
| No migrated-core physical bypass | Inspected task/server wiring (`main.py:511`), Container chat (`container.py:808`), Graph firewall (`attempt_executor.py:698-722`), master orchestrator's durable Graph entry. Bounded lifecycle/egress/wiring gates passed. Reachability of all compatibility callers remains **UNVERIFIED**; no reachable server bypass was demonstrated. |
| Persistence and Events/Invocations correlated across retry/recovery | Correlation/one-trace tests exercise real executor context and SQLite Events; ambiguous-effect test retains original Invocation IDs; PostgreSQL spine plus real HTTP task SIGKILL/restart passed. End-to-end PostgreSQL Event+Invocation correlation over crash/retry remains **UNVERIFIED**. |
| #1169/#1170/#1194 close first | Exact supplied issue snapshot entries are closed, with dates recorded above. No remote mutation or re-enumeration. |

No new scheduler, execution/store/event authority, or authorization path was
introduced. ADR b36a's renewal/reclaim extension to f383 is respected. The broad
issue wording is not used to remove compatibility paths without establishing
reachability and ownership first.

## Handoff

**NEEDS-DEEP-REVIEW for complete issue acceptance.** The prior environmental
block is resolved using local PostgreSQL; it should not trigger another Docker-
blocked rerun. The named audit/test-step/vulture failures do not reproduce on
this HEAD. Do not invent lockfile, ledger or runtime edits to manufacture a fix.
The whole multi-package CI `test` job was not reproduced; the named audit step
and relevant execution/persistence suites were. Request an exact newer failing
step log if the queue still reports `test: failure`.

This round changes only `docs/issue-42-repair-822379dc.md`. No tests were added,
removed or changed, so no test inventory delta is required. Fresh test runs
above total **2,127 passed, 3 skipped** (six SQLite teardown warnings). Driver
results are recorded separately and are not added to that total.

Next bounded review: establish migrated-path reachability around the remaining
compatibility fallback and add/execute real-Pg Invocation concurrency plus chat
crash/terminal-write correlation evidence. Existing passing fake-pool tests and
in-memory chat tests are not substitutes. No concrete production regression was
found in this CI-repair round.

The dedicated database/role `auto42_822379dc` is retained for follow-up. Its
migration-suite fixture ends at base; migrate it again before using spine tests.
The mode-0600 environment file is local-only and must never be committed or
published. No server processes were started in the background by this worker.

Progress: `{checked: 1, done: 1, skipped: 0, errors: 0, next: bounded acceptance
review above}`. One assigned repair item revalidated; initial tooling/environment
errors were resolved or explicitly skipped. Local report commit required; no
push, PR, integration approval or issue closure.
