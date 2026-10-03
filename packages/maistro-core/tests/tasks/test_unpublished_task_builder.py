"""Characterize unpublished Task receipt construction before Run admission (#1866)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

import maistro.tasks.queue as queue_mod
from maistro.tasks.lanes import Lane
from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import _build_unpublished_task, TaskQueue


_FIXED_TIME = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def _build(
    request: TaskCreate,
    *,
    task_id: str = "task-fixed",
    user_id: str = "",
    idempotency_key: str | None = None,
):
    return _build_unpublished_task(
        request,
        task_id=task_id,
        created_at=_FIXED_TIME,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )


def test_unpublished_builder_preserves_all_receipt_fields_and_defaults() -> None:
    minimal = _build(TaskCreate(description="minimal"), task_id="minimal-task")
    assert minimal.model_dump(mode="json") == {
        "task_id": "minimal-task",
        "status": "queued",
        "description": "minimal",
        "workspace": "/tmp/maistro-workspace",
        "user_id": "",
        "service_principal_id": None,
        "delegation_id": None,
        "actor_kind": "user",
        "task_type": None,
        "agent_id": None,
        "capability": None,
        "program_context": None,
        "branch": None,
        "constraints": [],
        "tier": 2,
        "lane": "background-task",
        "priority_tier": "P2",
        "session_id": None,
        "idempotency_key": None,
        "run_id": None,
        "phase": "queued",
        "progress": {"subtasks": 0, "completed": 0, "current": ""},
        "result": None,
        "created_at": "2026-10-03T12:00:00Z",
        "started_at": None,
        "completed_at": None,
    }

    request = TaskCreate(
        description="full",
        workspace="/tmp/workspace",
        tier=4,
        branch="feature/full",
        constraints=["tests", "lint"],
        lane=Lane.LIVE,
        priority_tier="P0",
        task_type="code",
        agent_id="mason",
        capability="python",
        program_context={"ticket": "1866"},
        session_id="session-1",
        idempotency_key="request-key",
        user_id="request-owner",
        service_principal_id="request-service",
        delegation_id="request-delegation",
        actor_kind="user",
    )
    full = _build_unpublished_task(
        request,
        task_id="full-task",
        created_at=_FIXED_TIME,
        user_id="call-owner",
        service_principal_id="call-service",
        delegation_id="call-delegation",
        actor_kind="service",
        idempotency_key="supplied-key",
    )
    assert full.model_dump(mode="json") == {
        "task_id": "full-task",
        "status": "queued",
        "description": "full",
        "workspace": "/tmp/workspace",
        "user_id": "call-owner",
        "service_principal_id": "call-service",
        "delegation_id": "call-delegation",
        "actor_kind": "service",
        "task_type": "code",
        "agent_id": "mason",
        "capability": "python",
        "program_context": {"ticket": "1866"},
        "branch": "feature/full",
        "constraints": ["tests", "lint"],
        "tier": 4,
        "lane": "live-chat",
        "priority_tier": "P0",
        "session_id": "session-1",
        "idempotency_key": "supplied-key",
        "run_id": None,
        "phase": "queued",
        "progress": {"subtasks": 0, "completed": 0, "current": ""},
        "result": None,
        "created_at": "2026-10-03T12:00:00Z",
        "started_at": None,
        "completed_at": None,
    }
    assert minimal.progress is not full.progress


def test_unpublished_builder_preserves_owner_precedence() -> None:
    request_owner = TaskCreate(description="owned", user_id="request-owner")

    assert _build(request_owner, user_id="call-owner").user_id == "call-owner"
    assert _build(request_owner).user_id == "request-owner"
    assert _build(TaskCreate(description="anonymous")).user_id == ""


def test_unpublished_builder_preserves_supplied_key_and_copies_constraints() -> None:
    request = TaskCreate(
        description="copy",
        constraints=["one"],
        idempotency_key="request-key",
    )

    explicit = _build(request, task_id="explicit", idempotency_key="supplied-key")
    omitted = _build(request, task_id="omitted", idempotency_key=None)

    assert explicit.idempotency_key == "supplied-key"
    assert omitted.idempotency_key is None
    explicit.constraints.append("two")
    assert request.constraints == ["one"]
    assert omitted.constraints == ["one"]


def test_unpublished_builder_has_no_clock_id_or_publication_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bomb(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("pure builder reached an external side effect")

    class _BombClock:
        now = staticmethod(_bomb)

    request = TaskCreate(
        description="pure",
        constraints=["keep"],
        program_context={"nested": ["value"]},
    )
    before = request.model_dump(mode="json")

    monkeypatch.setattr(queue_mod.TaskResponse, "new_id", staticmethod(_bomb))
    monkeypatch.setattr(queue_mod, "datetime", _BombClock)
    monkeypatch.setattr(queue_mod, "get_async_session_factory", _bomb)

    task = _build_unpublished_task(
        request,
        task_id="provided-id",
        created_at=_FIXED_TIME,
        idempotency_key=None,
    )

    assert request.model_dump(mode="json") == before
    assert task.task_id == "provided-id"
    assert task.created_at == _FIXED_TIME
    assert task.run_id is None
    assert task.result is None
    assert task.started_at is None
    assert task.completed_at is None


async def test_submit_once_uses_builder_before_existing_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Counter:
        def __init__(self) -> None:
            self.calls = 0

        def inc(self) -> None:
            self.calls += 1

    class _FixedClock:
        @staticmethod
        def now(tz: Any) -> datetime:
            assert tz is UTC
            return _FIXED_TIME

    class _BlockingAdmitter:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.seen = None
            self.workspace_id: str | None = None

        async def admit(self, task: Any, *, workspace_id: str | None = None) -> str:
            self.seen = task
            self.workspace_id = workspace_id
            self.entered.set()
            await self.release.wait()
            return "run-fixed"

    class _FailingAdmitter:
        async def admit(self, _task: Any, *, workspace_id: str | None = None) -> str:
            raise RuntimeError(f"admission failed for {workspace_id}")

    original_builder = queue_mod._build_unpublished_task
    builder_calls: list[dict[str, Any]] = []

    def _wrapped_builder(request: TaskCreate, **kwargs: Any):
        builder_calls.append({"request": request, **kwargs})
        return original_builder(request, **kwargs)

    submitted_counter = _Counter()
    active_counter = _Counter()
    monkeypatch.setattr(queue_mod.TaskResponse, "new_id", staticmethod(lambda: "fixed-task-id"))
    monkeypatch.setattr(queue_mod, "datetime", _FixedClock)
    monkeypatch.setattr(queue_mod, "_build_unpublished_task", _wrapped_builder)
    monkeypatch.setattr(queue_mod, "tasks_submitted_total", submitted_counter)
    monkeypatch.setattr(queue_mod, "active_tasks", active_counter)

    admitter = _BlockingAdmitter()
    queue = TaskQueue(admitter=admitter)
    persisted_run_ids: list[str | None] = []
    monkeypatch.setattr(queue, "_persist", lambda task: persisted_run_ids.append(task.run_id))

    submission = asyncio.create_task(
        queue._submit_once(
            TaskCreate(description="ordered", user_id="request-owner"),
            user_id="principal",
            workspace_id="workspace-1",
            idempotency_key="key-1",
        )
    )
    await admitter.entered.wait()

    assert len(builder_calls) == 1
    assert builder_calls[0]["task_id"] == "fixed-task-id"
    assert builder_calls[0]["created_at"] == _FIXED_TIME
    assert builder_calls[0]["user_id"] == "principal"
    assert builder_calls[0]["idempotency_key"] == "key-1"
    assert admitter.seen is not None
    assert admitter.seen.task_id == "fixed-task-id"
    assert admitter.seen.run_id is None
    assert admitter.workspace_id == "workspace-1"
    assert queue.get("fixed-task-id") is None
    assert queue._pending.empty()
    assert persisted_run_ids == []
    assert submitted_counter.calls == 0
    assert active_counter.calls == 0

    admitter.release.set()
    task = await submission

    assert task.run_id == "run-fixed"
    assert queue.get("fixed-task-id") is task
    assert queue._pending.qsize() == 1
    assert persisted_run_ids == ["run-fixed"]
    assert submitted_counter.calls == 1
    assert active_counter.calls == 1

    builder_calls.clear()
    failed = TaskQueue(admitter=_FailingAdmitter())
    failed_persisted: list[str | None] = []
    monkeypatch.setattr(failed, "_persist", lambda task: failed_persisted.append(task.run_id))
    submitted_before = submitted_counter.calls
    active_before = active_counter.calls

    with pytest.raises(RuntimeError, match="admission failed"):
        await failed._submit_once(
            TaskCreate(description="refused"),
            user_id="principal",
            workspace_id="workspace-2",
        )

    assert len(builder_calls) == 1
    assert failed.get("fixed-task-id") is None
    assert failed._pending.empty()
    assert failed_persisted == []
    assert submitted_counter.calls == submitted_before
    assert active_counter.calls == active_before
