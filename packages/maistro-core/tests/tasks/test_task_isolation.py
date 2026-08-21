"""Per-user task isolation on TaskQueue."""

from __future__ import annotations

import pytest

from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import TaskQueue


@pytest.fixture
def queue() -> TaskQueue:
    return TaskQueue()


@pytest.mark.asyncio
async def test_users_cannot_see_each_others_tasks(queue: TaskQueue) -> None:
    alice_task = await queue.submit(
        TaskCreate(description="Alice work"),
        user_id="alice",
    )
    await queue.submit(TaskCreate(description="Bob work"), user_id="bob")

    assert queue.get(alice_task.task_id, user_id="alice") is not None
    assert queue.get(alice_task.task_id, user_id="bob") is None


@pytest.mark.asyncio
async def test_list_tasks_filtered_by_user(queue: TaskQueue) -> None:
    await queue.submit(TaskCreate(description="A1"), user_id="alice")
    await queue.submit(TaskCreate(description="B1"), user_id="bob")
    await queue.submit(TaskCreate(description="A2"), user_id="alice")

    alice_items, _ = queue.list_tasks(limit=50, user_id="alice")
    bob_items, _ = queue.list_tasks(limit=50, user_id="bob")

    assert len(alice_items) == 2
    assert len(bob_items) == 1
    assert all(t.user_id == "alice" for t in alice_items)
