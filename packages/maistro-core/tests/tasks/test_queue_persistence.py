"""ADR-018: TaskRecord upserts at the queue's submit/update_status boundaries.

The contract has three edges: no DB configured → the queue behaves exactly as
before; DB configured → submit and every status change upsert a snapshot; a
failing write is logged and swallowed, never surfaced to the caller.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import maistro.tasks.queue as queue_mod
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue


class _FakeSession:
    def __init__(self, sink: list[Any], *, fail: bool = False) -> None:
        self._sink = sink
        self._fail = fail

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def merge(self, record: Any) -> Any:
        if self._fail:
            raise RuntimeError("synthetic database outage")
        self._sink.append(record)
        return record

    async def commit(self) -> None:
        return None


def _install_factory(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> list[Any]:
    sink: list[Any] = []
    monkeypatch.setattr(
        queue_mod,
        "get_async_session_factory",
        lambda: lambda: _FakeSession(sink, fail=fail),
    )
    return sink


async def _drain(queue: TaskQueue) -> None:
    while queue._persist_writes:
        await asyncio.gather(*queue._persist_writes)


async def test_no_database_keeps_queue_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_mod, "get_async_session_factory", lambda: None)
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="offline"))
    assert await queue.update_status(task.task_id, TaskStatus.PLANNING)
    assert queue._persist_writes == set()


async def test_submit_and_status_changes_upsert_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _install_factory(monkeypatch)
    queue = TaskQueue()

    task = await queue.submit(TaskCreate(description="persist me", workspace="ws"))
    await queue.update_status(task.task_id, TaskStatus.PLANNING)
    await queue.update_status(task.task_id, TaskStatus.CODING)
    await queue.update_status(task.task_id, TaskStatus.COMPLETED)
    await _drain(queue)

    assert [record.status for record in sink] == [
        "queued",
        "planning",
        "coding",
        "completed",
    ]
    final = sink[-1]
    assert final.id == task.task_id
    assert final.description == "persist me"
    assert final.workspace == "ws"
    assert final.started_at is not None and final.started_at.tzinfo is None
    assert final.completed_at is not None and final.completed_at.tzinfo is None


async def test_rejected_transition_persists_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _install_factory(monkeypatch)
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="x"))
    await _drain(queue)
    submitted = len(sink)

    assert not await queue.update_status(task.task_id, TaskStatus.QUEUED)
    await _drain(queue)
    assert len(sink) == submitted


async def test_database_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_factory(monkeypatch, fail=True)
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="doomed write"))
    assert await queue.update_status(task.task_id, TaskStatus.PLANNING)
    await _drain(queue)
    # The queue's own state is authoritative and untouched by the DB outage.
    stored = queue.get(task.task_id)
    assert stored is not None and stored.status is TaskStatus.PLANNING
