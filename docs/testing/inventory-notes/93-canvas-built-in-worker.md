---
inventory-delta:
  packages/maistro-canvas/tests: +27
---
# #93 Built-in Canvas worker service and runner concurrency

Ships the deployment shape for the built-in Canvas worker (SPEC-203, M3-B3):
a `maistro-canvas-worker` console-script service configured entirely through
the environment, plus bounded concurrency for `CanvasJobRunner` so one
deployment can progress independent ready jobs in parallel.

Test deltas:

- Added `packages/maistro-canvas/tests/test_worker_service.py` (14 tests):
  environment parsing fails loudly per-variable; `module:attr` adapter
  targets resolve as instance/class/zero-arg-factory/async-factory and
  refuse malformed targets; the migration preflight refuses an unmigrated
  database naming `alembic upgrade head` (and passes when every required
  spine + canvas table exists); the production composition path provably
  builds through `build_canvas_runtime` with the resolved adapters, scope,
  `prime=False` consumer wiring, and configured concurrency — including the
  SQLAlchemy engine receiving the `postgresql+asyncpg://`-qualified URL while
  the asyncpg pool keeps the plain one (`sqlalchemy_asyncpg_url`; found live:
  the first real start against a migrated database crashed in engine creation
  on the documented `postgresql://` DSN form); `run_worker` starts and
  gracefully stops the composed runner, closes the pool and engine, and exits
  1 when the runner dies mid-flight; `main` maps config errors to exit 2 and
  crashes to exit 1.
- Added `packages/maistro-canvas/tests/test_runner_concurrency.py` (8 tests):
  two ready jobs execute overlapping inside one runner (behavioral barrier,
  not task-structure assertions); `stop()` halts claiming and drains the
  claimed job to DONE; cancelling `start()` reaches the in-flight provider
  call and leaves the receipt leased for the reaper (no fake terminal
  status); extra concurrency slots never double-claim a single job;
  the running loop's reap sweep reclaims a dead worker's expired lease and
  re-executes it under its next attempt; a tick task that raises is
  retrieved and logged without killing the loop; a cancelled tick is
  retrieved silently; non-positive concurrency is rejected.

No existing tests were removed. The `start()` restructure (concurrent tick
tasks with drain-on-stop and cancellation parity with the serial design)
is covered by the pre-existing runner, shutdown-bound, canonical-executor,
migration-parity, and scope-conformance suites, which all still pass.

Postgres-backed legs remain with the existing PG-gated suites
(`test_store_scope_conformance.py`, `test_migration_parity.py`); this note's
tests deliberately prove the service wiring with in-memory substitutes, not
the queue semantics.

## Repair round: reconcile honored a live lease for driver-hydrated receipts

Live re-verification of the two-worker claim race (real pgvector Postgres,
migrated spine, two `maistro-canvas-worker` processes) falsified the
"each claimed exactly once" evidence: reproducibly (1-in-5 runs), worker B's
`reconcile_admissions` requeued worker A's *live-leased* RUNNING receipt back
to PENDING while A was mid-execution (Postgres statement log: `UPDATE ... SET
status='pending'` written with A's unexpired `lease_expires_at` and fences
`expected_status='running', expected_attempts='1'`), so `claim_next_pending`
handed the same physical job to B — attempt 2, provider dispatched twice.

Root cause: `PgCanvasStore._coerce_job` hydrated the status column as a plain
`str`, and `_project_receipt`'s live-lease guard tested `job.status is
JobStatus.RUNNING`. Identity comparison against a `StrEnum` member is always
false for a plain string, so the guard silently never fired on the
PostgreSQL path (the #1531 regression tests pass because in-memory doubles
hydrate real enum members). Fixed twice over:

- `store._coerce_job` now hydrates through `JobStatus(...)`
  (`_coerce_job_status`, tolerant of unrecognized legacy values), so every
  consumer sees the shape the in-memory stores produce;
- `_project_receipt` compares with `==` (exact for `StrEnum`/`str`) instead
  of `is` for the receipt-status tests, so the invariant no longer depends
  on which store hydrated the record.

Test deltas (this round):

- Added to `packages/maistro-canvas/tests/test_canonical_execution.py`
  (+2 tests): `test_recovery_leaves_a_string_status_live_leased_receipt_alone`
  pins the exact production shape (receipt whose `status` is the plain string
  `'running'` with a live 300s lease is left alone — no requeue, no write);
  `test_recovery_requeues_a_string_status_receipt_whose_lease_expired` proves
  the equality fix did not become a blanket "never touch RUNNING": an expired
  lease under a plain-string status is still requeued.

After the fix, 8/8 live two-worker races (2 jobs, 2 workers, fast polls)
claim exactly once each (attempts=1 everywhere); the kill -9 recovery leg
re-proved one Run with attempt 1 `cancelled` and attempt 2 `completed`.

## Repair round: pin the status-hydration hinge directly (diff-coverage gap)

Re-running CI's exact diff-coverage gate
(`scripts/check-diff-coverage.py coverage.xml --base <develop>`) against the
no-services canvas producer failed: `store.py` measured 60% of its 5 changed
lines (floor 90%) — lines 128-129, the `except ValueError` legacy-value
fallback of `_coerce_job_status`, are reachable only through a live driver
row, and no test called the helper directly. The original lane had no direct
coverage for it either; the prior round's evidence never ran this gate.

Test deltas (this round):

- Added to `packages/maistro-canvas/tests/test_canonical_execution.py`
  (+1 test): `test_receipt_status_hydration_coerces_driver_strings_and_passes_legacy_through`
  pins both branches of the hydration hinge — a driver-shaped plain string
  hydrates to the `JobStatus` member (through `_coerce_job`, the real row
  coercion path), and an unrecognized legacy value passes through as a plain
  string instead of crashing a read path.

## Repair round: reject adapter targets the executor cannot call

`resolve_target` accepts whatever a `module:attr` target returns, including a
factory's `None`. The worker's executor awaits `image_client.generate` /
`.refine`, calls `model_registry.is_registered` / `.get_default_draft`, and
awaits `warden.scan_prompt`; an adapter missing one of those composed cleanly
and failed only inside a claimed job — spending that job's retry budget and
terminalizing its canonical Run as failed. `compose_runtime` now validates
every resolved adapter and raises `WorkerConfigError` at startup instead.

Test deltas (this round):

- Added to `packages/maistro-canvas/tests/test_worker_service.py` (+1 test):
  `test_compose_runtime_rejects_adapters_the_executor_cannot_call` drives
  `compose_runtime` with a target that resolves to an object missing `refine`,
  a factory that resolves to `None`, and a warden target missing
  `scan_prompt`, asserting each is a startup `WorkerConfigError` rather than a
  first-claim crash.

(The prior round's hydration test above was collected but not reflected in
this note's `inventory-delta`; the front matter now records both it and this
round's guard test, `+25` -> `+27`.)
