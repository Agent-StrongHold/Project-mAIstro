---
id: SPEC-226
title: "Hive task backend boundary: MaistroServerTaskBackend replaces direct TaskRunner construction"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-096
implements:
  - maistro-engine#ADR-096
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/hive-conductor/backend/tests/test_engine_service.py
  - packages/hive-conductor/backend/tests/test_no_taskrunner_boundary.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-226: Hive task backend boundary

## Context

ADR-096 establishes that maistro-server is the canonical backend for production task
execution and that Hive Conductor must not own a production `TaskRunner` — Hive is a
UI/BFF adapter that calls maistro-server for real execution. As implemented today,
`packages/hive-conductor/backend/services/engine.py::EngineService.start()`
unconditionally constructs `maistro.tasks.queue.TaskQueue` and
`maistro.tasks.runner.TaskRunner` in-process and runs the engineering/PM executor
locally — there is no `HIVE_MODE=demo` gate and no call into maistro-server's
`/tasks` API. This is a standing violation of an Accepted ADR, not just an
unimplemented feature.

## Goals

- Define a `TaskBackend` protocol that `EngineService` depends on instead of a
  concrete `TaskQueue`/`TaskRunner` pair.
- Provide `MaistroServerTaskBackend`, an httpx-based implementation that calls
  maistro-server's existing `POST/GET/DELETE /tasks` endpoints
  (`packages/maistro-server/src/maistro_server/api/tasks.py`) — this is the
  production path.
- Preserve the existing in-process `TaskQueue` + `TaskRunner` path as
  `LocalTaskBackend`, explicitly gated behind `settings.hive_mode == "demo"` per
  ADR-096's allowance for a non-production demo/dev mode.
- Default (`hive_mode="production"`) must call `MaistroServerTaskBackend` against
  `settings.maistro_base_url`.

## Non-goals

- Streaming task events over a websocket/SSE from maistro-server — `iter_task_events`
  on `MaistroServerTaskBackend` polls `GET /tasks/{id}` on an interval; a push-based
  event stream is a separate concern (ADR-086).
- Changing maistro-server's `/tasks` API surface.
- Migrating the PM-mode (`run_pm_task`) executor itself — that still runs wherever
  the task is actually executed (maistro-server in production, in-process in demo).

## Decision

`packages/hive-conductor/backend/adapters/task_backend.py` (new):

```python
class TaskBackend(Protocol):
    async def submit(self, create: TaskCreate, *, user_id: str) -> TaskRecord: ...
    def get(self, task_id: str, *, user_id: str | None = None) -> TaskRecord | None: ...
    def list_tasks(self, *, user_id: str | None = None) -> list[TaskRecord]: ...
    async def cancel(self, task_id: str) -> bool: ...
    async def iter_events(self, task_id: str) -> AsyncIterator[dict[str, Any]]: ...
    async def stop(self) -> None: ...

class LocalTaskBackend:
    """Wraps TaskQueue + TaskRunner in-process. Demo/dev mode only (ADR-096)."""

class MaistroServerTaskBackend:
    """httpx client against maistro-server's /tasks API. Production default."""
```

`EngineService.start()` selects the backend:

```python
if settings.hive_mode == "demo":
    self._backend = LocalTaskBackend(executor=...)
else:
    self._backend = MaistroServerTaskBackend(
        base_url=settings.maistro_base_url,
        api_key=settings.maistro_router_api_key,
    )
```

`submit_task`/`get_task`/`list_tasks`/`iter_task_events`/`stop` on `EngineService`
delegate to `self._backend` instead of touching `TaskQueue`/`TaskRunner` directly.
`config.py` gains `hive_mode: Literal["production", "demo"] = "production"`.

## Acceptance criteria

- [x] `hive_mode` defaults to `"production"`; in that mode `EngineService` never
      imports or constructs `maistro.tasks.runner.TaskRunner`.
- [x] `hive_mode="demo"` preserves current in-process behavior (existing
      `test_engine_service.py` demo-mode cases continue to pass).
- [x] `MaistroServerTaskBackend.submit/get/list/cancel` map 1:1 onto
      `POST /tasks`, `GET /tasks/{id}`, `GET /tasks`, `DELETE /tasks/{id}`.
- [x] A static boundary test asserts no production code path under
      `packages/hive-conductor/backend/` imports `TaskRunner` outside of
      `LocalTaskBackend` itself.

## Testing

- `packages/hive-conductor/backend/tests/test_no_taskrunner_boundary.py` (new) —
  greps the backend source tree for `TaskRunner` imports outside
  `adapters/task_backend.py`.
- `packages/hive-conductor/backend/tests/test_engine_service.py` — extended with
  `MaistroServerTaskBackend` cases using a mocked httpx transport, and existing
  demo-mode cases re-pointed at `LocalTaskBackend`.

## Open questions

- Whether `iter_task_events` polling interval should be configurable per-deployment
  or a fixed constant — left as a fixed constant for this spec; revisit if
  maistro-server gains a push-based event stream (ADR-086).

## References

- [ADR-096: Hive Conductor / maistro-server boundary](../adr/ADR-096-hive-server-boundary.md)
- `packages/hive-conductor/backend/services/engine.py`
- `packages/maistro-server/src/maistro_server/api/tasks.py`
