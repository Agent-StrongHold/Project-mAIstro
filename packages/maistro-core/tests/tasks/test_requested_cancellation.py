"""A requested cancellation stops the running work (#1242).

`DELETE /tasks/{id}` terminalized the receipt and reported success while the
runner's coroutine ran on: the executor the caller cancelled kept consuming
compute and writing into the workspace, and when it eventually finished its
result was attached to a receipt that already said CANCELLED. The queue had no
handle to the physical work, so a cancellation could only rewrite the receipt.

These tests reproduce that failure mode and hold the fix: `TaskQueue.cancel`
must reach the registered execution and stop it, the unwinding work must not
overwrite the truthful receipt, and a shutdown cancellation — a different
event with a different meaning — must keep recording a failure exactly as it
did before.
"""

from __future__ import annotations

import asyncio

from maistro.agents.types import ConductorOutput
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.execution import TaskAttemptExecutor
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner


def _ok(answer: str = "done") -> ConductorOutput:
    return ConductorOutput(success=True, final_answer=answer)


async def _wait_until(predicate, *, timeout: float = 10.0) -> None:
    """Poll a condition the dispatcher satisfies asynchronously."""
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never became true")


async def test_cancel_stops_the_running_work() -> None:
    """The regression: cancel() returning True while the executor runs on.

    Without the fix the executor's sleep completes and the runner writes a
    result onto the cancelled receipt — both asserted impossible below.
    """
    queue = TaskQueue()
    started = asyncio.Event()
    completed = False

    async def executor(_request: TaskCreate) -> ConductorOutput:
        nonlocal completed
        started.set()
        await asyncio.sleep(0.5)
        completed = True
        return _ok()

    runner = TaskRunner(queue, executor)
    await runner.start()
    try:
        task = await queue.submit(TaskCreate(description="long job"))
        await asyncio.wait_for(started.wait(), timeout=10)

        assert await queue.cancel(task.task_id) is True
        # Long enough that the executor's 0.5s sleep would have fired had the
        # cancellation not reached it.
        await asyncio.sleep(1.0)

        assert completed is False, "the executor ran to completion after cancel"
        receipt = queue.get(task.task_id)
        assert receipt is not None
        assert receipt.status is TaskStatus.CANCELLED
        assert receipt.result is None, "a result was written onto a cancelled receipt"
        await asyncio.sleep(0)
        assert queue._executions == {}, "a finished execution was left registered"
    finally:
        await runner.stop(drain_timeout=2.0)


async def test_cancel_does_not_report_success_before_work_settles() -> None:
    """A cancellation-suppressing executor cannot make cancellation succeed.

    The old queue returned True after a short settle timeout even though this
    executor was still alive. Once it eventually returns, its result must not
    be attached to the already-cancelled receipt.
    """
    queue = TaskQueue()
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def executor(_request: TaskCreate) -> ConductorOutput:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()
            finished.set()
            return _ok("ignored cancellation")
        raise AssertionError("unreachable")

    runner = TaskRunner(queue, executor)
    await runner.start()
    try:
        task = await queue.submit(TaskCreate(description="must settle first"))
        await asyncio.wait_for(started.wait(), timeout=10)

        assert await queue.cancel(task.task_id, settle_timeout=0.01) is False
        assert cancellation_seen.is_set()
        assert not finished.is_set()
        receipt = queue.get(task.task_id)
        assert receipt is not None
        assert receipt.status is TaskStatus.CANCELLED
        assert receipt.result is None

        release.set()
        await asyncio.wait_for(finished.wait(), timeout=10)
        await asyncio.sleep(0)  # flush the execution's done callback
        assert queue.get(task.task_id).result is None
        assert queue.get(task.task_id).status is TaskStatus.CANCELLED
    finally:
        release.set()
        await runner.stop(drain_timeout=2.0)


async def test_cancelled_work_cannot_attach_a_late_failure() -> None:
    """A work item that handles cancellation and then fails cannot rewrite the receipt.

    The cancellation request wins the receipt transition. If the executor later
    raises while unwinding, both the claim and runner failure paths must respect
    that terminal state instead of attaching an error result to it.
    """
    queue = TaskQueue()
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def executor(_request: TaskCreate) -> ConductorOutput:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()
            finished.set()
            raise RuntimeError("late failure after cancellation") from None
        raise AssertionError("unreachable")

    runner = TaskRunner(queue, executor)
    await runner.start()
    try:
        task = await queue.submit(TaskCreate(description="late failure"))
        await asyncio.wait_for(started.wait(), timeout=10)

        assert await queue.cancel(task.task_id, settle_timeout=0.01) is False
        assert cancellation_seen.is_set()

        release.set()
        await asyncio.wait_for(finished.wait(), timeout=10)
        receipt = queue.get(task.task_id)
        assert receipt is not None
        assert receipt.status is TaskStatus.CANCELLED
        assert receipt.result is None
    finally:
        release.set()
        await runner.stop(drain_timeout=2.0)


async def test_cancel_reaches_work_still_waiting_for_a_lane() -> None:
    """A dispatched task parked at the lane gate is also running work the
    caller asked to stop — it must never get its permit and execute."""
    queue = TaskQueue()
    release = asyncio.Event()
    calls: list[str] = []

    async def executor(request: TaskCreate) -> ConductorOutput:
        calls.append(request.description)
        if request.description == "holder":
            await release.wait()
        return _ok("ok")

    # max_workers=2 sizes the gate as live=1/background=0/shared=1, so the
    # second BACKGROUND task parks at the gate until the first finishes.
    runner = TaskRunner(queue, executor, max_workers=2)
    await runner.start()
    try:
        holder = await queue.submit(TaskCreate(description="holder"))
        waiting = await queue.submit(TaskCreate(description="waiting"))
        await _wait_until(lambda: calls == ["holder"])

        assert await queue.cancel(waiting.task_id) is True
        assert queue.get(waiting.task_id).status is TaskStatus.CANCELLED

        release.set()
        await runner.stop(drain_timeout=2.0)
        # After the holder releases its permit, a cancellation that never
        # reached the gate-waiting task would let it acquire and run here.
        assert calls == ["holder"], f"the cancelled task ran: {calls}"
        assert queue.get(holder.task_id).status is TaskStatus.COMPLETED
    finally:
        release.set()


async def test_cancel_a_queued_task_and_it_never_starts() -> None:
    """Cancelling before dispatch has no registered execution to stop — the
    receipt transition must still succeed, and the dispatcher must refuse the
    stale dequeue rather than running the work anyway."""
    queue = TaskQueue()
    calls: list[str] = []

    async def executor(request: TaskCreate) -> ConductorOutput:
        calls.append(request.description)
        return _ok()

    task = await queue.submit(TaskCreate(description="never runs"))
    assert await queue.cancel(task.task_id) is True

    runner = TaskRunner(queue, executor)
    await runner.start()
    try:
        # Let the dispatcher drain the stale pending entry and hit the refusal.
        await asyncio.sleep(0.2)
        assert calls == []
        assert queue.get(task.task_id).status is TaskStatus.CANCELLED
    finally:
        await runner.stop(drain_timeout=1.0)


async def test_cancelling_finished_work_reports_false() -> None:
    """Work that reached a terminal state on its own cannot be cancelled: the
    response must not claim a cancellation that did not happen."""
    queue = TaskQueue()

    async def executor(_request: TaskCreate) -> ConductorOutput:
        return _ok()

    runner = TaskRunner(queue, executor)
    task = await queue.submit(TaskCreate(description="quick"))

    await runner._execute_task(task.task_id)
    assert queue.get(task.task_id).status is TaskStatus.COMPLETED

    assert await queue.cancel(task.task_id) is False
    assert queue.get(task.task_id).status is TaskStatus.COMPLETED


async def test_shutdown_cancellation_still_records_a_failure() -> None:
    """A shutdown cancellation is not a requested one: the receipt is not
    CANCELLED, so the worker's CancelledError must still record the failure
    (and its result) exactly as it did before the fix."""
    queue = TaskQueue()
    started = asyncio.Event()

    async def executor(_request: TaskCreate) -> ConductorOutput:
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    runner = TaskRunner(queue, executor)
    await runner.start()
    task = await queue.submit(TaskCreate(description="shutdown fodder"))
    await asyncio.wait_for(started.wait(), timeout=10)

    await runner.stop(drain_timeout=0.05)

    receipt = queue.get(task.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.FAILED
    assert receipt.result is not None
    assert receipt.result.error == "Task cancelled during shutdown"


async def test_a_requested_cancellation_records_a_cancelled_attempt_and_run() -> None:
    """The canonical spine must agree with the receipt. `queue.cancel` is the
    product cancellation path — DELETE /tasks/{id} — and it must leave the
    Attempt CANCELLED and the Run CANCELLED, not merely flip the receipt."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    started = asyncio.Event()

    async def executor(_request: TaskCreate) -> ConductorOutput:
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("the cancelled work must not finish")

    runner = TaskRunner(queue, executor=executor, attempts=TaskAttemptExecutor(runs))
    await runner.start()
    try:
        task = await queue.submit(TaskCreate(description="Fix the parser"))
        await asyncio.wait_for(started.wait(), timeout=10)

        assert await queue.cancel(task.task_id) is True

        receipt = queue.get(task.task_id)
        assert receipt is not None
        assert receipt.status is TaskStatus.CANCELLED
        run = await runs.get_run(task.run_id or "")
        assert run is not None
        assert run.status is RunStatus.CANCELLED
        node_runs = await runs.list_node_runs(task.run_id or "")
        assert len(node_runs) == 1
        node_run = await runs.get_node_run(node_runs[0].node_run_id)
        assert node_run is not None
        assert node_run.status is RunStatus.CANCELLED
        attempts = await runs.list_attempts(node_runs[0].node_run_id)
        assert [a.status for a in attempts] == [AttemptStatus.CANCELLED]
    finally:
        await runner.stop(drain_timeout=2.0)


async def test_the_execution_registry_does_not_retain_finished_work() -> None:
    """Unregistration runs from the execution's done callback: a completed
    task must leave no stale handle for a later cancel to trip over."""
    queue = TaskQueue()

    async def executor(_request: TaskCreate) -> ConductorOutput:
        return _ok()

    runner = TaskRunner(queue, executor)
    await runner.start()
    try:
        task = await queue.submit(TaskCreate(description="quick"))
        await _wait_until(lambda: queue.get(task.task_id).status is TaskStatus.COMPLETED)
        await asyncio.sleep(0)  # flush done callbacks
        assert queue._executions == {}
        assert await queue.cancel(task.task_id) is False
    finally:
        await runner.stop(drain_timeout=1.0)


async def test_a_cancelled_receipt_keeps_no_result_after_the_work_stopped() -> None:
    """The secondary defect the regression surfaced: the runner's success
    branch attached its result to a receipt the API had already reported
    cancelled. `set_result` stays lawful only for work still in the race —
    a receipt terminalized by cancellation must end with none."""
    queue = TaskQueue()
    started = asyncio.Event()
    finished = asyncio.Event()

    async def executor(_request: TaskCreate) -> ConductorOutput:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            finished.set()
            raise
        return _ok()

    runner = TaskRunner(queue, executor)
    await runner.start()
    try:
        task = await queue.submit(TaskCreate(description="results must not follow"))
        await asyncio.wait_for(started.wait(), timeout=10)
        assert await queue.cancel(task.task_id) is True
        assert finished.is_set()
        receipt = queue.get(task.task_id)
        assert receipt is not None
        assert receipt.status is TaskStatus.CANCELLED
        assert receipt.result is None
    finally:
        await runner.stop(drain_timeout=2.0)
