---
inventory-delta:
  packages/maistro-server/tests: +1
---
Issue #91 (M3-B1, durable/recoverable task queue): the closure evidence the
KNOWN-GAPS task-persistence entry asked for — a product-path restart E2E in
`packages/maistro-server/tests/test_task_restart_recovery.py`. One test,
three real server processes over one migrated PostgreSQL spine:

1. the stock app admits a task through `POST /v1/tasks` and is then
   SIGKILLed with the task still QUEUED (worker start substituted at the
   single `TaskRunner.start` seam — admission, lifespan, API and queue are
   untouched);
2. a restarted stock process rehydrates the admission in lifespan startup
   (`queue.recover(run_store)`), announces `task_recovered`, executes the
   task exactly once on the *same* canonical Run (verified as one
   `canonical_runs` row with one NodeRun and one Attempt, read straight
   from the database), and reaches a truthful `completed` receipt;
3. a third stock process reads the terminal outcome off the durable
   operator projection (`GET /v1/runs/{run_id}`) — receipts are the living
   queue's answer (ADR-018), so the fresh process is asked for the Run —
   and a byte-identical resubmission replays the original
   task_id/run_id with the drained `completed` receipt through the durable
   idempotency claim store (#1176) without executing anything again.

This is the forced-death (SIGKILL, no drain) evidence #91's acceptance
names, complementing the SIGTERM half pinned by `test_sigterm_shutdown.py`.
Needs `MAISTRO_TEST_PG_DSN`; skips without one like every other
PostgreSQL-backed suite in the repository.

Repair-round addendum (2026-10-01, CI evidence run 36835563331/36835563261):
the first merge-queue evaluation of this note's test recorded a SKIP —
`MAISTRO_TEST_PG_DSN` was unset in the deterministic check battery, so the
closure evidence this note describes had not actually executed. Executed for
real in the repair round against a migrated pgvector:pg18 container:
`test_queued_task_survives_sigkill_and_executes_exactly_once_after_restart`
passed in 41.7s, with `packages/maistro-core/tests/tasks` (402),
`packages/maistro-core/tests/runs/test_consumption.py` (37, the
`TickAccounting` attempted/succeeded/failed/parked/skipped contract) and
`test_sigterm_shutdown.py` (3) all green on the same spine. Same round, two
CI-gate repairs on untouched-by-#91 surfaces: the two whole-repository-scan
tests in `tests/test_check_execution_lifecycles.py` (measured 27s and 31.5s
bare, past the gate's 30s budget the moment coverage traces the script) now
carry explicit `@pytest.mark.timeout(180)` stated margins — node IDs and
counts unchanged, `tests/` inventory still 4264 — and the three pip-based
images (Dockerfile, Dockerfile.research, hive-conductor) set
`PIP_DEFAULT_TIMEOUT=60`/`PIP_RETRIES=10` after both buildx attempts of the
research build died inside pip on 15s-default `files.pythonhosted.org` read
timeouts (the same requirements resolve cleanly — proven by pip --dry-run
and by building both builder stages locally).
