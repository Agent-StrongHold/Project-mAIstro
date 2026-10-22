---
inventory-delta:
  packages/maistro-server/tests: +2
---

# #819 — SIGTERM drains through the server lifespan before process exit

## Defect

`maistro_server.main` installed its own SIGTERM/SIGINT handler during lifespan
startup (`loop.add_signal_handler`), which **replaced** Uvicorn's `handle_exit`
(asyncio allows one handler per signal). `should_exit` was therefore never set:
the server ignored SIGTERM, none of the lifespan shutdown block ran (task
drain, sandbox container cleanup, shared-client close, usage-log flush, DB
engine disposal), and a container grace deadline ended in SIGKILL with
sandboxes and pooled connections still live.

Reproduced at signal level on `develop@55be1459` before the fix: a Uvicorn
subprocess of `maistro_server.main:app` was **still alive 20s after SIGTERM**
(probe in job dir `00525566ffe242c19b2a7cafdc609c7e/sigterm_probe.py`),
with no `maistro_engine_stopped` and no "Application shutdown complete".

## Fix

- `packages/maistro-server/src/maistro_server/main.py` — the lifespan no
  longer touches signal handling. Uvicorn remains the process-exit signal
  authority (AC-1); the drain composes through the existing lifespan `finally`
  block via `_runner.stop(drain_timeout=SHUTDOWN_DRAIN_TIMEOUT)` (AC-4: the
  timeout is the explicit 30s module constant; tasks the deadline cancels are
  marked FAILED — `tasks_cancelled_on_shutdown` — bounded by
  `TaskRunner.CANCELLED_SETTLE_TIMEOUT`, and shutdown continues to normal
  process exit). The now-dead `_graceful_shutdown` is removed.
- `docs/install/deployment-topology.md` — documents the SIGTERM contract the
  tests prove: drain window, FAILED failure state, sandbox/client/engine
  teardown order, Uvicorn's signal-death exit status, and how operators must
  size `stop_grace_period` (AC-5). Not a grace-period extension — the stop
  condition prohibits masking; the fix makes shutdown actually run.

## Tests

**+1 `packages/maistro-server/tests/api/test_main.py`** (net: class replaced,
count unchanged):

- `TestSignalAuthority::test_lifespan_does_not_install_signal_handlers` —
  drives the real `lifespan()` with a spy event loop and asserts
  `add_signal_handler` is never called, i.e. the lifespan cannot take the
  server's signal authority back. Replaces the deleted `TestGracefulShutdown`
  class, whose contract (`_graceful_shutdown`) no longer exists.

**+1 `packages/maistro-server/tests/test_sigterm_shutdown.py`** — three
signal-level integration tests driving real OS signals at real Uvicorn
subprocesses of `maistro_server.main:app` (the shape `entrypoint.py` runs):

- `TestSigtermReachesLifespanShutdown` (AC-2) — SIGTERM terminates the
  process promptly, and the output proves Uvicorn ran lifespan shutdown
  ("Application shutdown complete") *and* MAIstro's own callbacks completed
  (`maistro_engine_stopped`, `all_sandboxes_cleaned_up`,
  `task_runner_stopped`).
- `TestSigtermDrainsInflightTask` (AC-4) — a task admitted through the real
  `POST /v1/tasks` door and held open by a substituted executor
  (`conductor.run_task`, the runner's own injection seam;
  `SHUTDOWN_DRAIN_TIMEOUT` shrunk to 3s by the driver so the bounded wait is
  observable): SIGTERM waits out the drain window, records the failure state
  (`draining_active_tasks` → `tasks_cancelled_on_shutdown`), and the process
  still exits normally.
- `TestStopRestartLeavesNoOrphanedSandboxes` (AC-3, docker-gated with the
  same `_docker_ready()` convention as
  `packages/maistro-bootstrap/tests/test_container_sandbox.py`) — the driver
  seeds the sandbox registry with a **real** Docker container, SIGTERM stops
  the server, `docker inspect` proves the MAIstro-owned container was
  destroyed (no orphans), then a fresh instance restarts, reports
  `startup_complete` and still sees no MAIstro-owned containers.

Exit-status note baked into the tests: Uvicorn ≥0.34 `capture_signals`
re-raises the captured signal after a signal-driven graceful shutdown, so a
clean stop reports either exit 0 or death-by-SIGTERM; both are asserted as
clean (`_clean_signal_exit`).

## Validation on this head

- `uv run pytest packages/maistro-server/tests/api/test_main.py` — 19 passed.
- `test_sigterm_shutdown.py::TestSigtermReachesLifespanShutdown` — passed.
- `test_sigterm_shutdown.py::TestSigtermDrainsInflightTask` — passed.
- `TestStopRestartLeavesNoOrphanedSandboxes` — Docker daemon in the lane
  environment could not start new containers (hangs even a minimal
  `docker run` while other lanes' stacks run); the test is docker-gated and
  must be proven where the daemon is healthy. Recorded as residual risk, not
  skipped-by-silence.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
