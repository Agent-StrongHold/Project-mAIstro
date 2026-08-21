"""Tests for TaskQueue — events, pagination, pruning."""

from __future__ import annotations

import asyncio

import pytest

from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue


@pytest.fixture()
def queue():
    return TaskQueue()


async def test_submit_and_get(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test task"))
    assert task.status == TaskStatus.QUEUED
    retrieved = queue.get(task.task_id)
    assert retrieved is not None
    assert retrieved.description == "test task"


async def test_status_transition(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"))
    assert await queue.update_status(task.task_id, TaskStatus.PLANNING)
    assert queue.get(task.task_id).status == TaskStatus.PLANNING


async def test_invalid_transition_rejected(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"))
    # Can't go from QUEUED directly to COMPLETED
    assert not await queue.update_status(task.task_id, TaskStatus.COMPLETED)


async def test_event_notification(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"))

    notified = False

    async def waiter():
        nonlocal notified
        await queue.wait_for_update(task.task_id)
        notified = True

    bg_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    await queue.update_status(task.task_id, TaskStatus.PLANNING)
    await asyncio.sleep(0.01)
    assert notified
    assert bg_task.done()


async def test_cursor_pagination(queue: TaskQueue):
    for i in range(5):
        await queue.submit(TaskCreate(description=f"task {i}"))

    items, cursor = queue.list_tasks(limit=2)
    assert len(items) == 2
    assert cursor is not None

    items2, _cursor2 = queue.list_tasks(limit=2, cursor=cursor)
    assert len(items2) == 2
    assert items2[0].task_id != items[0].task_id


async def test_cancel(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"))
    assert await queue.cancel(task.task_id)
    assert queue.get(task.task_id).status == TaskStatus.CANCELLED


async def test_get_nonexistent(queue: TaskQueue):
    assert queue.get("nonexistent-id") is None


async def test_full_lifecycle(queue: TaskQueue):
    """Test a task through all phases: queued -> planning -> coding -> completed."""
    task = await queue.submit(TaskCreate(description="full lifecycle"))
    for status in [
        TaskStatus.PLANNING,
        TaskStatus.CODING,
        TaskStatus.COMPLETED,
    ]:
        assert await queue.update_status(task.task_id, status), f"Failed to transition to {status}"
    assert queue.get(task.task_id).status == TaskStatus.COMPLETED
    assert queue.get(task.task_id).completed_at is not None


async def test_cancel_not_possible_after_completion(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"))
    for status in [
        TaskStatus.PLANNING,
        TaskStatus.CODING,
        TaskStatus.COMPLETED,
    ]:
        await queue.update_status(task.task_id, status)
    assert not await queue.cancel(task.task_id)


async def test_list_empty_queue(queue: TaskQueue):
    items, cursor = queue.list_tasks()
    assert items == []
    assert cursor is None
