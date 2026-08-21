"""Tests for TaskQueue — events, pagination, pruning."""

from __future__ import annotations

import asyncio

import pytest

from maistro.tasks.models import TaskCreate, TaskResult, TaskStatus
from maistro.tasks.queue import MAX_TASK_STORE_SIZE, PRUNE_TARGET, TaskQueue, get_task_queue


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


async def test_update_status_missing_task_returns_false(queue: TaskQueue):
    assert not await queue.update_status("nonexistent-id", TaskStatus.PLANNING)


async def test_update_progress_missing_task_is_noop(queue: TaskQueue):
    from maistro.tasks.models import TaskProgress

    queue.update_progress("nonexistent-id", TaskProgress())

    assert queue.get("nonexistent-id") is None
    assert queue._tasks == {}


async def test_update_progress_existing_task_notifies(queue: TaskQueue):
    from maistro.tasks.models import TaskProgress

    task = await queue.submit(TaskCreate(description="test"))
    queue.update_progress(task.task_id, TaskProgress(current="halfway"))
    assert queue.get(task.task_id).progress.current == "halfway"


async def test_set_result_missing_task_is_noop(queue: TaskQueue):
    queue.set_result("nonexistent-id", TaskResult(error="boom"))

    assert queue.get("nonexistent-id") is None
    assert queue._tasks == {}


async def test_set_result_existing_task_sets_value(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"))
    queue.set_result(task.task_id, TaskResult(error="boom"))
    assert queue.get(task.task_id).result.error == "boom"


async def test_remove_nonexistent_task_returns_false(queue: TaskQueue):
    assert not queue.remove("nonexistent-id")


async def test_remove_non_terminal_task_returns_false(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"))
    assert not queue.remove(task.task_id)


async def test_remove_terminal_task_succeeds(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"))
    for status in [TaskStatus.PLANNING, TaskStatus.CODING, TaskStatus.COMPLETED]:
        await queue.update_status(task.task_id, status)
    assert queue.remove(task.task_id)
    assert queue.get(task.task_id) is None


async def test_remove_where_filters_by_status(queue: TaskQueue):
    completed = await queue.submit(TaskCreate(description="completed"))
    for status in [TaskStatus.PLANNING, TaskStatus.CODING, TaskStatus.COMPLETED]:
        await queue.update_status(completed.task_id, status)
    cancelled = await queue.submit(TaskCreate(description="cancelled"))
    await queue.cancel(cancelled.task_id)
    still_queued = await queue.submit(TaskCreate(description="queued"))

    removed = queue.remove_where(status=TaskStatus.COMPLETED)
    assert removed == 1
    assert queue.get(completed.task_id) is None
    assert queue.get(cancelled.task_id) is not None
    assert queue.get(still_queued.task_id) is not None


async def test_remove_where_no_filter_removes_all_terminal(queue: TaskQueue):
    completed = await queue.submit(TaskCreate(description="completed"))
    for status in [TaskStatus.PLANNING, TaskStatus.CODING, TaskStatus.COMPLETED]:
        await queue.update_status(completed.task_id, status)
    cancelled = await queue.submit(TaskCreate(description="cancelled"))
    await queue.cancel(cancelled.task_id)

    removed = queue.remove_where()
    assert removed == 2


async def test_next_task_returns_submitted_task_id(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"))
    task_id = await queue.next_task()
    assert task_id == task.task_id


async def test_list_tasks_filters_by_user_id(queue: TaskQueue):
    mine = await queue.submit(TaskCreate(description="mine"), user_id="alice")
    await queue.submit(TaskCreate(description="theirs"), user_id="bob")

    items, _cursor = queue.list_tasks(user_id="alice")
    assert len(items) == 1
    assert items[0].task_id == mine.task_id


async def test_get_with_user_id_mismatch_returns_none(queue: TaskQueue):
    task = await queue.submit(TaskCreate(description="test"), user_id="alice")
    assert queue.get(task.task_id, user_id="bob") is None
    assert queue.get(task.task_id, user_id="alice") is not None


async def test_maybe_prune_removes_oldest_terminal_tasks():
    queue = TaskQueue()
    # Fill past the max store size with already-terminal tasks so pruning fires.
    for i in range(MAX_TASK_STORE_SIZE + 1):
        task = await queue.submit(TaskCreate(description=f"task {i}"))
        async with queue._lock:
            queue._tasks[task.task_id].status = TaskStatus.COMPLETED
    queue._maybe_prune()
    assert len(queue._tasks) <= PRUNE_TARGET + 1


async def test_maybe_prune_skips_when_under_limit(queue: TaskQueue):
    await queue.submit(TaskCreate(description="test"))
    before = len(queue._tasks)
    queue._maybe_prune()
    assert len(queue._tasks) == before


class TestClaim:
    async def test_claim_missing_task_raises(self, queue: TaskQueue):
        with pytest.raises(ValueError, match="not found"):
            async with queue.claim("nonexistent-id"):
                pass

    async def test_claim_already_claimed_raises(self, queue: TaskQueue):
        task = await queue.submit(TaskCreate(description="test"))
        async with queue.claim(task.task_id):
            with pytest.raises(ValueError, match="already claimed"):
                async with queue.claim(task.task_id):
                    pass

    async def test_claim_success_yields_task_and_releases(self, queue: TaskQueue):
        task = await queue.submit(TaskCreate(description="test"))
        async with queue.claim(task.task_id) as claimed:
            assert claimed.task_id == task.task_id
            assert task.task_id in queue._claimed
        assert task.task_id not in queue._claimed

    async def test_claim_exception_marks_task_failed(self, queue: TaskQueue):
        task = await queue.submit(TaskCreate(description="test"))
        await queue.update_status(task.task_id, TaskStatus.PLANNING)
        with pytest.raises(RuntimeError, match="boom"):
            async with queue.claim(task.task_id):
                raise RuntimeError("boom")
        result_task = queue.get(task.task_id)
        assert result_task.status == TaskStatus.FAILED
        assert result_task.result.error == "boom"
        assert task.task_id not in queue._claimed


def test_get_task_queue_returns_singleton():
    import maistro.tasks.queue as queue_module

    queue_module._queue = None
    first = get_task_queue()
    second = get_task_queue()
    assert first is second
    queue_module._queue = None
