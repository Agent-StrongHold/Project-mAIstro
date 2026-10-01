---
inventory-delta:
  packages/maistro-canvas/tests: +10
---

# Issue #398 — Canvas retry bound, store contract, and queue health evidence

Implements the M4 Canvas acceptance: bounded retries with durable backoff and
poison-job handling, one typed job-store contract checked against production
and fakes, and queue health exposing stuck/retry/exhausted jobs.

New evidence:

- `test_job_store_contract.py` runs the shared contract bodies
  (`canvas_testing/job_store_contract.py`, shared test scaffolding under
  `packages/maistro-canvas/tests/`) against two legs: the
  in-memory fake (always) and the production `PgCanvasStore` against a real
  PostgreSQL server in a throwaway schema (skips without
  `MAISTRO_TEST_PG_DSN`; `MAISTRO_REQUIRE_PG_LEGS` fails instead of skipping,
  and that fail-closed behavior is itself tested). Bodies cover: claim gates
  on `next_retry_at` and clears it on claim; the reaper writes the shared
  backoff schedule durably; an over-budget pending row is never claimed but
  is surfaced by the reaper for canonical terminalization; queue stats mirror
  exactly the states the store's own writers produce, org-scoped; both legs
  structurally implement the `CanvasJobStore` protocol. Running identical
  bodies against both legs is the fake/production drift guard.
- `test_job_runner_lifecycle.py` gains the runner-level poison test (a
  permanent auth failure terminalizes on first failure without spending the
  remaining attempt budget, through the same canonical
  `fail_job_execution` path as exhaustion) and the runner-level backoff test
  (a retryable failure requeues behind the durable gate; the store's claim
  refuses it until the delay passes). The `InMemoryJobStore` fake moved to
  the shared testing module with production-mirroring backoff semantics; the
  lifecycle suite pins its timing with `ZERO_BACKOFF`.
- `test_store_scope_conformance.py` keeps pinning scope/fencing with the zero
  schedule (fencing tests requeue-then-reclaim immediately) and shares the
  canvas DDL with the contract suite via
  `canvas_testing/canvas_schema.py`, so the two cannot describe
  different schemas.
- `test_canvas_store_migration.py` extends the adopted-schema leg: the
  alembic chain must leave `next_retry_at` on `generation_jobs` (migration
  048, idempotent like 044; downgrade drops it).

The PostgreSQL legs ran against a real server (pgvector/pg16 container) in
this job: 486 passed / 3 skipped for the whole canvas suite with
`MAISTRO_TEST_PG_DSN` set, including the contract postgres leg, the full
alembic chain (fresh, adopted, re-applied, downgrade) with migration 048, and
the scope-conformance legs.
