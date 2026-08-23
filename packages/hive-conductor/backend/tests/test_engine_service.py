"""Boy Scout coverage: services/engine.py (was 27%).

Covers:
- TaskRecord property views (id, name, description, mission_status,
  progress with/without subtasks, current_step, created_at, started_at,
  completed_at, error)
- _STATUS_MAP coverage via mission_status property
- EngineService singleton lifecycle (get/start/stop/get-when-not-started)
- EngineService.start with no router_api_key → StubAgentPort
- EngineService.stop with no runner is safe
- submit_task: no queue → RuntimeError
- submit_task: gated capability without confirmed program_context →
  ValueError (work-item-draft guard)
- submit_task: non-gated capability submits and returns TaskRecord
- get_task / list_tasks / delete_task / clear_tasks no-queue branches
- clear_tasks with status filter (failed / completed)
- iter_task_events: yields update for non-terminal, returns on terminal
"""

from __future__ import annotations

import pathlib
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True)
def _reset_singleton():
    import services.engine as e

    prev = e._singleton
    e._singleton = None
    yield
    e._singleton = prev


# --- TaskRecord properties ----------------------------------------------


def _fake_task(**overrides: Any) -> Any:
    defaults = {
        "task_id": "t-1",
        "description": "ship the feature",
        "status": "queued",
        "progress": SimpleNamespace(subtasks=4, completed=2, current="planning"),
        "phase": "",
        "created_at": datetime(2026, 5, 22, tzinfo=UTC),
        "started_at": datetime(2026, 5, 22, 1, tzinfo=UTC),
        "completed_at": None,
        "result": None,
    }
    defaults.update(overrides)
    t = SimpleNamespace(**defaults)
    return t


def test_task_record_basic_properties() -> None:
    from services.engine import TaskRecord

    rec = TaskRecord(_fake_task())
    assert rec.id == "t-1"
    assert rec.name == "ship the feature"
    assert rec.description == "ship the feature"
    assert rec.mission_status == "pending"  # queued → pending
    assert rec.progress == 0.5  # 2/4
    assert rec.current_step == "planning"
    assert rec.started_at is not None
    assert rec.completed_at is None
    assert rec.error is None


def test_task_record_status_mapping() -> None:
    """Each status string maps to the right mission_status."""
    from services.engine import TaskRecord

    mapping = {
        "queued": "pending",
        "planning": "running",
        "coding": "running",
        "reviewing": "running",
        "testing": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "failed",
    }
    for src, expected in mapping.items():
        rec = TaskRecord(_fake_task(status=src))
        assert rec.mission_status == expected


def test_task_record_unknown_status_falls_back_to_pending() -> None:
    from services.engine import TaskRecord

    rec = TaskRecord(_fake_task(status="weird"))
    assert rec.mission_status == "pending"


def test_task_record_progress_no_subtasks_falls_back() -> None:
    from services.engine import TaskRecord

    # No subtasks; not completed → 0.0
    rec = TaskRecord(
        _fake_task(
            progress=SimpleNamespace(subtasks=0, completed=0, current=""),
            status="queued",
        )
    )
    assert rec.progress == 0.0

    # No subtasks; completed → 1.0
    rec = TaskRecord(
        _fake_task(
            progress=SimpleNamespace(subtasks=0, completed=0, current=""),
            status="completed",
        )
    )
    assert rec.progress == 1.0


def test_task_record_current_step_falls_back_to_phase() -> None:
    from services.engine import TaskRecord

    rec = TaskRecord(
        _fake_task(
            progress=SimpleNamespace(subtasks=0, completed=0, current=""),
            phase="phase-x",
        )
    )
    assert rec.current_step == "phase-x"


def test_task_record_error_when_result_set() -> None:
    from services.engine import TaskRecord

    rec = TaskRecord(_fake_task(result=SimpleNamespace(error="boom")))
    assert rec.error == "boom"


def test_task_record_short_name_takes_first_60_chars() -> None:
    from services.engine import TaskRecord

    long = "x" * 200
    rec = TaskRecord(_fake_task(description=long))
    assert rec.name == "x" * 60


# --- EngineService singleton ---------------------------------------------


def test_get_engine_raises_when_not_started() -> None:
    from services.engine import get_engine

    with pytest.raises(RuntimeError, match="EngineService not started"):
        get_engine()


async def test_start_with_no_router_key_uses_stub_agent_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.engine import EngineService

    class _Settings:
        maistro_router_api_key = ""
        maistro_base_url = "http://localhost:8000"
        hive_mode = "production"

    svc = EngineService()
    await svc.start(_Settings())  # type: ignore[arg-type]
    assert svc._agent_port is not None
    # type name reflects stub fallback
    assert type(svc._agent_port).__name__ == "StubAgentPort"
    # production hive_mode → MaistroServerTaskBackend, never a TaskRunner
    assert type(svc._backend).__name__ == "MaistroServerTaskBackend"


async def test_start_in_demo_mode_uses_local_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.engine import EngineService

    class _Settings:
        maistro_router_api_key = ""
        maistro_base_url = "http://localhost:8000"
        hive_mode = "demo"

    # Stub out TaskQueue/TaskRunner so .start doesn't try to spawn real ones
    class _Q:
        def __init__(self, *, admitter: Any = None) -> None:
            self.admitter = admitter

    class _R:
        def __init__(self, q: Any, executor: Any, attempts: Any = None) -> None:
            pass

        async def start(self) -> None:
            pass

    import types

    queue_mod = types.ModuleType("maistro.tasks.queue")
    queue_mod.TaskQueue = _Q  # type: ignore[attr-defined]
    runner_mod = types.ModuleType("maistro.tasks.runner")
    runner_mod.TaskRunner = _R  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.tasks.queue", queue_mod)
    monkeypatch.setitem(sys.modules, "maistro.tasks.runner", runner_mod)
    conductor_mod = types.ModuleType("maistro.agents.conductor")

    async def _stub_run_task(*a: Any, **kw: Any) -> Any:
        return None

    conductor_mod.run_task = _stub_run_task  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.agents.conductor", conductor_mod)

    svc = EngineService()
    await svc.start(_Settings())  # type: ignore[arg-type]
    assert type(svc._backend).__name__ == "LocalTaskBackend"


async def test_stop_with_no_backend_is_safe() -> None:
    from services.engine import EngineService

    svc = EngineService()
    # _backend is None — stop should be a no-op
    await svc.stop()


async def test_stop_with_failing_backend_is_swallowed() -> None:
    """The backend's stop() might raise; contextlib.suppress lets it pass."""
    from services.engine import EngineService

    class _Backend:
        async def stop(self) -> None:
            raise RuntimeError("synthetic")

    svc = EngineService()
    svc._backend = _Backend()
    await svc.stop()  # no raise


async def test_maistro_server_task_backend_submit_get_list_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MaistroServerTaskBackend maps 1:1 onto maistro-server's /tasks API."""
    import httpx
    from adapters.task_backend import MaistroServerTaskBackend

    from maistro.tasks.models import TaskCreate

    task_body = {
        "task_id": "srv-1",
        "status": "queued",
        "description": "ship it",
        "workspace": "/tmp/maistro-workspace",  # nosec B108 — static test fixture, mirrors TaskCreate's documented default
        "tier": 2,
        "phase": "queued",
        "progress": {"subtasks": 0, "completed": 0, "current": ""},
        "result": None,
        "created_at": "2026-06-20T00:00:00Z",
        "started_at": None,
        "completed_at": None,
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/tasks":
            return httpx.Response(
                202, json={"task_id": "srv-1", "status": "queued", "task": task_body}
            )
        if request.method == "GET" and request.url.path == "/tasks/srv-1":
            return httpx.Response(200, json=task_body)
        if request.method == "GET" and request.url.path == "/tasks":
            return httpx.Response(200, json={"items": [task_body], "next_cursor": None, "count": 1})
        if request.method == "DELETE" and request.url.path == "/tasks/srv-1":
            return httpx.Response(200, json={"cancelled": True})
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)

    backend = MaistroServerTaskBackend(base_url="http://maistro-server", api_key="k")

    _OrigAsyncClient = httpx.AsyncClient
    _OrigClient = httpx.Client
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _OrigAsyncClient(
            transport=transport, **{k: v for k, v in kw.items() if k != "transport"}
        ),
    )
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: _OrigClient(
            transport=transport, **{k: v for k, v in kw.items() if k != "transport"}
        ),
    )

    rec = await backend.submit(TaskCreate(description="ship it"), user_id="u1")
    assert rec.id == "srv-1"

    got = backend.get("srv-1")
    assert got is not None
    assert got.id == "srv-1"

    items = backend.list_tasks()
    assert [i.id for i in items] == ["srv-1"]

    cancelled = await backend.cancel("srv-1")
    assert cancelled is True


async def test_maistro_server_task_backend_get_missing_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from adapters.task_backend import MaistroServerTaskBackend

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    _OrigClient = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: _OrigClient(
            transport=transport, **{k: v for k, v in kw.items() if k != "transport"}
        ),
    )

    backend = MaistroServerTaskBackend(base_url="http://maistro-server", api_key=None)
    assert backend.get("missing") is None


# --- submit_task ---------------------------------------------------------


async def test_submit_task_no_queue_raises_runtime() -> None:
    from services.engine import EngineService

    svc = EngineService()
    with pytest.raises(RuntimeError, match="TaskQueue not available"):
        await svc.submit_task("n", "d")


async def test_submit_task_gated_capability_without_confirmed_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gated capability must come with `program_context.confirmed=True`."""
    from services.engine import EngineService

    import maistro.agents.pm_capabilities as caps

    monkeypatch.setattr(caps, "is_gated", lambda c: True)
    monkeypatch.setattr(caps, "normalize_capability", lambda c: c)

    svc = EngineService()
    svc._backend = SimpleNamespace()  # truthy
    with pytest.raises(ValueError, match="work-item draft flow"):
        await svc.submit_task(
            "n",
            "d",
            capability="any.gated_cap",
            program_context=None,  # not confirmed
        )


async def test_submit_task_success_returns_task_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.engine import EngineService, TaskRecord

    import maistro.agents.pm_capabilities as caps

    monkeypatch.setattr(caps, "is_gated", lambda c: False)
    monkeypatch.setattr(caps, "normalize_capability", lambda c: c)

    class _Backend:
        async def submit(self, body: Any, *, user_id: str = "") -> Any:
            return TaskRecord(_fake_task(task_id="new-task", description=body.description))

    svc = EngineService()
    svc._backend = _Backend()
    rec = await svc.submit_task(
        "n",
        "ship hello",
        task_type="intake",
        agent_id="intake",
        capability="route_to_pm_agent",
    )
    assert rec.id == "new-task"
    assert rec.description == "ship hello"


# --- get_task / list_tasks / delete_task / clear_tasks ------------------


def test_get_task_no_backend_returns_none() -> None:
    from services.engine import EngineService

    svc = EngineService()
    assert svc.get_task("any") is None


def test_get_task_with_backend_returns_record() -> None:
    from services.engine import EngineService, TaskRecord

    class _B:
        def get(self, tid: str, *, user_id: Any = None) -> Any:
            return TaskRecord(_fake_task(task_id=tid))

    svc = EngineService()
    svc._backend = _B()
    rec = svc.get_task("t-1")
    assert rec is not None
    assert rec.id == "t-1"


def test_get_task_missing_returns_none() -> None:
    from services.engine import EngineService

    class _B:
        def get(self, tid: str, *, user_id: Any = None) -> Any:
            return None

    svc = EngineService()
    svc._backend = _B()
    assert svc.get_task("missing") is None


def test_list_tasks_empty_backend_returns_empty() -> None:
    from services.engine import EngineService

    svc = EngineService()
    assert svc.list_tasks() == []


def test_list_tasks_passes_through_backend() -> None:
    from services.engine import EngineService, TaskRecord

    class _B:
        def list_tasks(self, *, user_id: Any = None) -> Any:
            return [TaskRecord(_fake_task(task_id="b")), TaskRecord(_fake_task(task_id="a"))]

    svc = EngineService()
    svc._backend = _B()
    out = svc.list_tasks()
    assert [r.id for r in out] == ["b", "a"]


def test_delete_task_no_backend_returns_false() -> None:
    from services.engine import EngineService

    svc = EngineService()
    assert svc.delete_task("any") is False


def test_delete_task_with_backend_passes_through() -> None:
    from services.engine import EngineService

    class _B:
        def remove(self, tid: str) -> bool:
            return tid == "exists"

    svc = EngineService()
    svc._backend = _B()
    assert svc.delete_task("exists") is True
    assert svc.delete_task("nope") is False


def test_clear_tasks_no_backend_returns_zero() -> None:
    from services.engine import EngineService

    svc = EngineService()
    assert svc.clear_tasks() == 0


def test_clear_tasks_filters_by_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.engine import EngineService

    captured: list[Any] = []

    class _B:
        def remove_where(self, *, status: Any) -> int:
            captured.append(status)
            return 3

    svc = EngineService()
    svc._backend = _B()
    from maistro.tasks.models import TaskStatus

    # No filter → status=None
    assert svc.clear_tasks() == 3
    assert captured[-1] is None
    # status="failed" → TaskStatus.FAILED
    svc.clear_tasks(status="failed")
    assert captured[-1] is TaskStatus.FAILED
    # status="completed" → TaskStatus.COMPLETED
    svc.clear_tasks(status="completed")
    assert captured[-1] is TaskStatus.COMPLETED


# --- iter_task_events --------------------------------------------------


async def test_iter_task_events_no_backend_returns_immediately() -> None:
    from services.engine import EngineService

    svc = EngineService()
    events = [ev async for ev in svc.iter_task_events("t-1")]
    assert events == []


async def test_iter_task_events_yields_then_terminates() -> None:
    from services.engine import EngineService

    async def _events(tid: str) -> AsyncIterator[dict[str, Any]]:
        yield {"id": tid, "status": "running", "progress": 0.0, "current_step": "planning"}
        yield {"id": tid, "status": "completed", "progress": 1.0, "current_step": "done"}

    class _B:
        def iter_events(self, tid: str) -> Any:
            return _events(tid)

    svc = EngineService()
    svc._backend = _B()
    events = [ev async for ev in svc.iter_task_events("t-1")]
    statuses = [e["status"] for e in events]
    assert statuses == ["running", "completed"]


async def test_iter_task_events_returns_when_task_disappears() -> None:
    from services.engine import EngineService

    async def _events(tid: str) -> AsyncIterator[dict[str, Any]]:
        for event in ():
            yield event

    class _B:
        def iter_events(self, tid: str) -> Any:
            return _events(tid)

    svc = EngineService()
    svc._backend = _B()
    events = [ev async for ev in svc.iter_task_events("missing")]
    assert events == []
