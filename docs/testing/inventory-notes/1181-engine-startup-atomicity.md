---
inventory-delta:
  packages/hive-conductor/backend/tests: +18
---
# 1181 — EngineService startup atomicity and health-visible failure

What moved and why: `packages/hive-conductor/backend/tests/test_engine_startup_atomicity.py`
is new (+18), covering the #1181 contract on `services/engine.py`. No existing
test was removed or renamed; `test_engine_service.py` only gained two restored
globals in its singleton-reset fixture (`_failed_startup` alongside
`_singleton`), so its counts are untouched.

The eighteen cases pin the parts of the boot contract that had no coverage
because the old code could not express them:

- failure injected at every startup stage (agent-port binding, outcome store,
  metrics reset, DAG recovery start, canonical recovery start, task backend in
  both demo and production shapes) raises, unwinds what earlier steps started,
  leaves the instance `startup_failed` with a type-qualified, bounded cause,
  and never publishes the singleton;
- a failed first start is retryable — the next `start_engine()` boots and
  publishes only after a clean run, and `stop()` reports `stopped`;
- the two documented optional degradations (bridge→stub fallback, capability
  wiring to baselines/SAFE_NOOP) surface as `degraded` with a visible cause
  instead of being invisible;
- `engine_health()` answers for a never-started, failed-but-unpublished, and
  published engine;
- `/health` carries the engine state (liveness stays 200 "ok"), while
  `/health/ready` answers 503 with `checks["engine"]` false for a failed or
  in-flight boot, and keeps the historical 200 for contexts that never run
  the app lifespan.

One test-design note worth keeping: these tests reset module globals with
direct assignment inside one autouse fixture, never `monkeypatch.setattr`, on
the globals that fixture owns. A `monkeypatch` teardown can finalize *after*
the module fixture's teardown, re-restoring the value it recorded — `None` —
over the fixture's correct restore, which silently uninstalled the conftest's
engine singleton for every later suite (caught by `test_m0_tool_containment`
and the chat-spine fixtures failing at setup in a full-suite run). The fixture
owns its globals; the tests never record them elsewhere.
