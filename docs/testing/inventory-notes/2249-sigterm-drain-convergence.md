---
inventory-delta:
  packages/maistro-server/tests: +10
---

# Issue #2249: SIGTERM lifespan shutdown never completes during drain

The soak lane (#860) found the engine's SIGTERM path non-convergent: the drain
window produced 6,579 5xx while the old process hung in shutdown, and only the
restart-always SIGKILL reaped it. Two waits had no deadline; both are now
bounded, and each bound is pinned by a test in this change.

## Defect 1 — Uvicorn's connection drain (`entrypoint.py`, `Dockerfile.research`)

Uvicorn's `Server.shutdown` runs `lifespan.shutdown()` — where MAIstro's whole
teardown lives — only *after* `_wait_tasks_to_complete` returns, and that
coroutine spins `while self.server_state.connections` under an
`asyncio.wait_for` whose timeout is `timeout_graceful_shutdown`. Every engine
launch path left it `None`: the entrypoint execed uvicorn without the flag and
`Dockerfile.research`'s CMD likewise. One wedged in-flight request or an open
streaming response — the shape a load generator's pooled clients produce
across a kill/drain phase — spun the loop forever, so the lifespan teardown
never ran at all.

Fix: the entrypoint builds its argv as data (`_uvicorn_args`) and carries
`--timeout-graceful-shutdown <n>` (default 10s, `MAISTRO_SHUTDOWN_CONNECTION_GRACE`
override), strictly below the shipped compose `stop_grace_period: 30s` so the
teardown keeps room to run; the research image CMD carries the same flag.
`test_uvicorn_args_include_the_graceful_shutdown_deadline` and
`test_connection_grace_parsing` pin the argv and the env parsing at the exact
seam the container execs.

## Defect 2 — unbounded teardown phases (`main.py`)

Inside `_runtime_lifespan`'s `finally`, several phases owned no deadline:
`cleanup_all_containers` (one bounded docker call per container, no bound on
the loop), `aclose_shared_clients`, `container.aclose`, `engine.dispose`, and
the usage-log flush. A docker daemon or database wedged by the same drain
conditions held shutdown open past SIGKILL.

Fix: `_teardown_phase` runs each step under `TEARDOWN_PHASE_TIMEOUT` (10s),
cancels a step that exceeds it with a `lifespan_teardown_phase_timeout`
warning, and logs — never raises — a failed phase, extending the best-effort
contract `_drain_queue_singleton` already had to every remaining phase. The
existing failure-path test's assertion moved from the flush-specific
`usage_log_flush_failed` event to the phase-attributed
`lifespan_teardown_phase_failed` (same contract: failure logged, shutdown
proceeds, `aclose` still awaited). `TestTeardownPhaseBound` pins hung-cancel,
fail-log and healthy-completion.

## End-to-end convergence proof

`test_sigterm_converges_with_wedged_inflight_request` reproduces the reported
defect shape in a real server process: a request in flight that never answers,
SIGTERM, then assertions that the graceful-shutdown deadline fired ("timeout
graceful shutdown exceeded"), that the process exited inside the deadline, and
that the lifespan teardown ran to `maistro_engine_stopped` — the callback that
never ran before the fix. Red-check against the pre-fix tree: the same
wedge-and-SIGTERM scenario on the unbounded argv left the process alive past
15s (killed by the harness), reproducing the hang the soak lane reported.
