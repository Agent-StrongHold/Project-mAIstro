"""PM fleet stub executor tests."""

from __future__ import annotations

import asyncio

import pytest

from maistro.agents.pm_runner import run_pm_task
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner


@pytest.fixture(autouse=True)
def _use_pm_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    # This module tests the PM fleet STUB executor; force the stub path so the
    # tests don't require a live MAISTRO/LITELLM gateway.
    monkeypatch.setenv("MAISTRO_PM_USE_STUBS", "1")


@pytest.mark.asyncio
async def test_run_pm_task_succeeds_without_llm() -> None:
    task = TaskCreate(
        description="[Intake Agent] create_initiative: Q3 rollout",
        task_type="intake",
        agent_id="intake",
        capability="create_initiative",
    )
    result = await run_pm_task(task)
    assert result.success is True
    assert "create_initiative" in result.final_answer


@pytest.mark.asyncio
async def test_pm_runner_via_task_queue() -> None:
    queue = TaskQueue()
    runner = TaskRunner(queue, executor=run_pm_task, max_workers=1)
    await runner.start()
    try:
        task = await queue.submit(
            TaskCreate(
                description="[Delivery Agent] detect_blockers: sprint 12",
                task_type="delivery",
                agent_id="delivery",
                capability="detect_blockers",
            ),
            user_id="demo",
        )
        for _ in range(50):
            snap = queue.get(task.task_id)
            assert snap is not None
            if snap.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                break
            await asyncio.sleep(0.05)
        final = queue.get(task.task_id)
        assert final is not None
        assert final.status == TaskStatus.COMPLETED
    finally:
        await runner.stop()
