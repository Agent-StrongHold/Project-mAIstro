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
