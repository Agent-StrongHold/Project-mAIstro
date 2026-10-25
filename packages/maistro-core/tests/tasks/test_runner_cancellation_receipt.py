"""A user-initiated cancellation must not be recorded as a shutdown failure (#1337).

`TaskQueue.cancel` cancels the canonical Run, which fences it CANCELLED and
signals the in-flight Attempt's runtime owner. The worker then sees
`CancelledError` in `_run_with_permit`, whose handler used to write the
"Task cancelled during shutdown" disposition unconditionally: the FAILED
transition was refused by the already-CANCELLED Run (and reconciled, #849),
but `set_result` and the progress webhook fired anyway, so a cancelled receipt
carried a shutdown failure that never happened.

The regressions drive the real public path — admission, Attempt seam, Runtime
and runner; no method patching. `TaskQueue.cancel` triggers the user
cancellation; `TaskRunner.stop(drain_timeout=0)` is the positive control: on
the wired stack the Attempt layer carries a drain cancellation up to the Run
as a cancellation, so the receipt must read CANCELLED there too, while on a
plain queue (no Run behind the receipt) the drain still records the shutdown
failure exactly as it always did.
"""

from __future__ import annotations

import asyncio

import pytest

from maistro.agents.types import ConductorOutput
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.execution import TaskAttemptExecutor
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.progress_webhook import ConductorProgressPayload
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner

#: Bound for polling a disposition that requires only event-loop turns. A
#: deadlock backstop, not a performance assertion.
SETTLE_TIMEOUT = 10.0


class _BlockedExecutor:
    """Stands in for real work: starts, then waits until cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def __call__(self, _request: TaskCreate) -> ConductorOutput:
        self.started.set()
        await asyncio.sleep(300)
        raise AssertionError("executor finished without being cancelled")  # pragma: no cover


class _RecordingWebhook:
    """Records every progress payload the runner emits."""

    def __init__(self) -> None:
        self.payloads: list[ConductorProgressPayload] = []
        self.closed = False

    async def notify(self, payload: ConductorProgressPayload) -> None:
        self.payloads.append(payload)

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
async def wired_runner():
    """The full public stack: admission, Attempt seam, runner, webhook sink."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    webhook = _RecordingWebhook()
    executor = _BlockedExecutor()
    runner = TaskRunner(
        queue,
        executor,
        progress_webhook=webhook,
        attempts=TaskAttemptExecutor(runs),
    )
    return runner, queue, runs, webhook, executor


@pytest.fixture
async def plain_runner():
    """No admitter, no Attempt seam: the receipt is all there is."""
    queue = TaskQueue()
    webhook = _RecordingWebhook()
    executor = _BlockedExecutor()
    runner = TaskRunner(queue, executor, progress_webhook=webhook)
    return runner, queue, webhook, executor


async def _wait_for(predicate, *, description: str) -> None:
    async with asyncio.timeout(SETTLE_TIMEOUT):
        while not predicate():
            await asyncio.sleep(0.01)
    assert predicate(), f"never settled: {description}"


async def _submit_and_start(queue: TaskQueue, runner: TaskRunner, executor: _BlockedExecutor):
    await runner.start()
    task = await queue.submit(TaskCreate(description="long running work"))
    await asyncio.wait_for(executor.started.wait(), timeout=SETTLE_TIMEOUT)
    return task


async def test_user_cancelled_task_does_not_claim_shutdown(wired_runner) -> None:
    runner, queue, runs, webhook, executor = wired_runner
    task = await _submit_and_start(queue, runner, executor)
    try:
        assert await queue.cancel(task.task_id) is True

        # The worker's CancelledError handler must have run to completion:
        # the receipt terminal and the worker gone from the active set.
        await _wait_for(
            lambda: (
                (snap := queue.get(task.task_id)) is not None
                and snap.status is TaskStatus.CANCELLED
                and not runner._active_tasks
            ),
            description="cancelled receipt after worker settled",
        )

        snap = queue.get(task.task_id)
        assert snap is not None
        assert snap.status is TaskStatus.CANCELLED
        # The reconciliation projects the Run's own cancellation outcome; the
        # one thing it must never carry is a shutdown failure.
        assert snap.result is None or snap.result.error != "Task cancelled during shutdown"

        run = await runs.get_run(task.run_id or "")
        assert run is not None
        assert run.status is RunStatus.CANCELLED

        assert webhook.payloads, "the worker must still report the real end state"
        assert all(
            payload.error != "Task cancelled during shutdown" for payload in webhook.payloads
        )
        assert webhook.payloads[-1].status == TaskStatus.CANCELLED.value
    finally:
        await runner.stop(drain_timeout=1)


async def test_drain_on_wired_stack_does_not_claim_shutdown(wired_runner) -> None:
    """A drain cancellation is carried up to the Run by the Attempt layer, so
    the receipt reconciles to CANCELLED — and must not claim shutdown either.
    """
    runner, queue, runs, webhook, executor = wired_runner
    task = await _submit_and_start(queue, runner, executor)

    await runner.stop(drain_timeout=0)

    snap = queue.get(task.task_id)
    assert snap is not None
    assert snap.status is TaskStatus.CANCELLED
    assert snap.result is None or snap.result.error != "Task cancelled during shutdown"

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.status is RunStatus.CANCELLED

    assert webhook.payloads
    assert all(payload.error != "Task cancelled during shutdown" for payload in webhook.payloads)
    assert webhook.payloads[-1].status == TaskStatus.CANCELLED.value


async def test_plain_queue_drain_still_records_shutdown_disposition(plain_runner) -> None:
    """Positive control: with no Run behind the receipt, a real drain keeps
    exactly the old shutdown failure — status, result and webhook."""
    runner, queue, webhook, executor = plain_runner
    task = await _submit_and_start(queue, runner, executor)

    await runner.stop(drain_timeout=0)

    snap = queue.get(task.task_id)
    assert snap is not None
    assert snap.status is TaskStatus.FAILED
    assert snap.result is not None
    assert snap.result.error == "Task cancelled during shutdown"

    assert any(payload.error == "Task cancelled during shutdown" for payload in webhook.payloads), (
        "a genuine shutdown must still reach the webhook as a failure"
    )
    assert webhook.payloads[-1].status == TaskStatus.FAILED.value
