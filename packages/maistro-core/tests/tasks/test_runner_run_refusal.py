"""A cancelled Run stops the work (#41 review).

`TaskRunner` ignored `update_status()`'s return value, so a Run cancelled before
its task was picked up still had the executor run: real work performed for a
cancelled Run, the receipt left QUEUED, and a result written afterwards
describing work nobody asked for.
"""

from __future__ import annotations

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner


class _Executor:
    """Records whether it was ever asked to do the work."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, request):
        self.calls += 1
        raise AssertionError("the executor must not run for a cancelled Run")


@pytest.fixture
async def wired():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    return queue, runs


async def test_a_cancelled_run_is_not_executed(wired) -> None:
    queue, runs = wired
    executor = _Executor()
    runner = TaskRunner(queue, executor=executor)
    task = await queue.submit(TaskCreate(description="one"))
    await runs.transition_run(task.run_id or "", RunStatus.CANCELLED)

    await runner._execute_task(task.task_id)

    assert executor.calls == 0


async def test_the_receipt_does_not_advance_past_a_cancelled_run(wired) -> None:
    queue, runs = wired
    runner = TaskRunner(queue, executor=_Executor())
    task = await queue.submit(TaskCreate(description="one"))
    await runs.transition_run(task.run_id or "", RunStatus.CANCELLED)

    await runner._execute_task(task.task_id)

    assert queue.get(task.task_id).status is TaskStatus.QUEUED  # type: ignore[union-attr]


async def test_an_ordinary_task_still_runs(wired) -> None:
    """The guard must not have cost the behaviour it protects."""
    queue, _runs = wired
    seen: list[str] = []

    async def executor(request):
        seen.append(request.description)

        class _Result:
            success = True
            code = None
            final_answer = ""

        return _Result()

    runner = TaskRunner(queue, executor=executor)
    task = await queue.submit(TaskCreate(description="ship it"))

    await runner._execute_task(task.task_id)

    assert seen == ["ship it"]
    assert queue.get(task.task_id).status is TaskStatus.COMPLETED  # type: ignore[union-attr]


async def test_a_run_cancelled_mid_flight_stops_before_the_executor(wired) -> None:
    """The *second* refusal check, which the first three tests never reach.

    `_execute_task` asks the Run for permission twice — once entering PLANNING
    and again entering CODING — because cancellation is not instantaneous: a
    Run admitted for planning can be cancelled while the plan is being built,
    and the executor call is the expensive, side-effecting step that must not
    happen after that. Every test above cancels *before* submission, so the
    first check returns and the second was never executed by anything.

    Cancelling from the progress-webhook hook is what puts the cancellation in
    that window: it runs after PLANNING is admitted and before CODING is
    requested, which is exactly the race the second check exists for.
    """
    queue, runs = wired
    executor = _Executor()
    runner = TaskRunner(queue, executor=executor)
    task = await queue.submit(TaskCreate(description="one"))

    async def _cancel_mid_flight(task_id: str) -> None:
        await runs.transition_run(task.run_id or "", RunStatus.CANCELLED)

    runner._emit_progress_webhook = _cancel_mid_flight  # type: ignore[method-assign]

    await runner._execute_task(task.task_id)

    assert executor.calls == 0, "the executor ran for a Run cancelled during planning"
    assert queue.get(task.task_id).status is TaskStatus.PLANNING  # type: ignore[union-attr]
