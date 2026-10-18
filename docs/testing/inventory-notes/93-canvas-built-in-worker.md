---
inventory-delta:
  packages/maistro-canvas/tests: +22
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
