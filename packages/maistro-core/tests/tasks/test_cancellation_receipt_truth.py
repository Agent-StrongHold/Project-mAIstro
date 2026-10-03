"""Cancellation receipts and webhooks follow their canonical Run (#1337)."""

from __future__ import annotations

import asyncio

import pytest

from maistro.agents.types import ConductorOutput
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.runtime import PythonExecutionRuntime
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.execution import TaskAttemptExecutor
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.progress_webhook import ConductorProgressPayload
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

pytestmark = pytest.mark.contract("behavioral")


class _RecordingWebhook:
    """Observe real runner notifications without making external requests."""

    def __init__(self) -> None:
        self.payloads: list[ConductorProgressPayload] = []
        self.terminal = asyncio.Event()

    async def notify(self, payload: ConductorProgressPayload) -> None:
        self.payloads.append(payload.model_copy(deep=True))
        if payload.status in ("cancelled", "failed", "completed"):
            self.terminal.set()

    async def aclose(self) -> None:
        pass


@pytest.mark.parametrize("cause", ["user", "shutdown"])
async def test_inflight_cancellation_receipt_matches_canonical_cause(cause: str) -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-cancellation-truth")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(
        admitter=TaskRunAdmitter(
            runs, workspace_id="ws-cancellation-truth", project_id=root.project_id
        )
    )
    runtime = PythonExecutionRuntime(max_concurrency=1)
    webhook = _RecordingWebhook()
    entered = asyncio.Event()
    cleaned_up = asyncio.Event()
    calls = 0

    async def executor(_request: TaskCreate) -> ConductorOutput:
        nonlocal calls
        calls += 1
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned_up.set()
        raise AssertionError("the blocked executor must not return a result")

    runner = TaskRunner(
        queue,
        executor=executor,
        max_workers=1,
        progress_webhook=webhook,
        attempts=TaskAttemptExecutor(runs, runtime=runtime),
    )
    task = await queue.submit(
        TaskCreate(description="Cancel this running task"),
        user_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert task.run_id is not None
    await runner.start()
    try:
        # Events define the interleaving. This timeout only bounds a deadlock.
        async with asyncio.timeout(10):
            await entered.wait()
            node_runs = await runs.list_node_runs(task.run_id)
            assert len(node_runs) == 1
            node = node_runs[0]
            before = await runs.list_attempts(node.node_run_id)
            assert len(before) == 1
            assert before[0].status is AttemptStatus.RUNNING

            if cause == "user":
                assert await queue.cancel(task.task_id) is True
            else:
                await runner.stop(drain_timeout=0)
            await webhook.terminal.wait()
            await cleaned_up.wait()

        run = await runs.get_run(task.run_id)
        receipt = queue.get(task.task_id)
        assert run is not None and receipt is not None
        expected = RunStatus.CANCELLED if cause == "user" else RunStatus.FAILED
        assert run.status is expected
        assert receipt.status.value == expected.value
        receipt_error = receipt.result.error if receipt.result else None
        assert receipt_error == run.error
        if cause == "user":
            assert "shutdown" not in (receipt_error or "").lower()
        else:
            assert receipt.status is TaskStatus.FAILED
            assert receipt_error == "Task cancelled during shutdown"

        terminal = [
            payload
            for payload in webhook.payloads
            if payload.status in ("cancelled", "failed", "completed")
        ]
        assert len(terminal) == 1
        assert terminal[0].task_id == task.task_id
        assert terminal[0].status == expected.value
        assert terminal[0].error == run.error
        after = await runs.list_attempts(node.node_run_id)
        assert len(after) == 1
        assert after[0].attempt_id == before[0].attempt_id
        assert after[0].ordinal == before[0].ordinal
        assert after[0].status is AttemptStatus.CANCELLED
        assert after[0].result is None
        assert calls == 1
        metrics = runtime.metrics()
        assert metrics.executions_cancelled == 1
        assert metrics.executions_completed == 0
        assert metrics.active_executions == metrics.active_slots == 0
    finally:
        await runner.stop(drain_timeout=0)
