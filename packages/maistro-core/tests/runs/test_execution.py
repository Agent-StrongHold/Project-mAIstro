from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    Attempt,
    AttemptExecutionService,
    AttemptStatus,
    InMemoryRunStore,
    RunStatus,
)
from maistro.runs.execution import ExecutionYielded
from maistro.runtime import PythonExecutionRuntime, RuntimeDeadlineExceeded


class RecordingRuntime(PythonExecutionRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.last_execution_id: str | None = None

    async def execute(
        self,
        work_item: Any,
        execution_context: Any,
        *,
        execution_id: str,
        executor: Any,
        timeout_s: float | None = None,
    ) -> Any:
        self.last_execution_id = execution_id
        return await super().execute(
            work_item,
            execution_context,
            execution_id=execution_id,
            executor=executor,
            timeout_s=timeout_s,
        )


async def _node_run() -> tuple[InMemoryRunStore, str, str]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    project = await project_store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Execution",
    )
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    return store, run.run_id, node_run.node_run_id


@pytest.mark.asyncio
async def test_attempt_id_is_runtime_execution_id_and_reconciles_after_terminal_persist() -> None:
    store, run_id, node_run_id = await _node_run()
    runtime = RecordingRuntime()
    reconciled: list[Attempt] = []

    async def reconcile(attempt: Attempt) -> None:
        persisted = await store.list_attempts(node_run_id)
        assert persisted[-1].status is AttemptStatus.COMPLETED
        assert persisted[-1].attempt_id == attempt.attempt_id
        logical = await store.get_node_run(node_run_id)
        assert logical is not None
        assert logical.status is RunStatus.COMPLETED
        reconciled.append(attempt)

    service = AttemptExecutionService(store=store, runtime=runtime, reconciler=reconcile)

    async def executor(work_item: Any, context: Any) -> dict[str, Any]:
        return {"work": work_item, "context": context}

    terminal = await service.execute(
        node_run_id,
        "work",
        {"run": "context"},
        executor=executor,
        executor_id="agent",
    )

    assert terminal.status is AttemptStatus.COMPLETED
    assert terminal.result == {"work": "work", "context": {"run": "context"}}
    assert runtime.last_execution_id == terminal.attempt_id
    assert reconciled == [terminal]

    stored_run = await store.get_run(run_id)
    assert stored_run is not None
    assert stored_run.status is RunStatus.COMPLETED
    assert stored_run.result == terminal.result


@pytest.mark.asyncio
async def test_executor_exception_persists_failed_attempt_and_parks_logical_state() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work: Any, _context: Any) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await service.execute(node_run_id, None, None, executor=executor)

    attempts = await store.list_attempts(node_run_id)
    assert attempts[-1].status is AttemptStatus.FAILED
    assert attempts[-1].error == "boom"

    node_run = await store.get_node_run(node_run_id)
    run = await store.get_run(run_id)
    assert node_run is not None and node_run.status is RunStatus.WAITING
    assert run is not None and run.status is RunStatus.WAITING


@pytest.mark.asyncio
async def test_executor_timeout_is_failed_attempt_not_runtime_timeout() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work: Any, _context: Any) -> None:
        raise TimeoutError("provider timed out")

    with pytest.raises(TimeoutError, match="provider timed out"):
        await service.execute(
            node_run_id,
            None,
            None,
            executor=executor,
            timeout_s=1,
        )

    attempts = await store.list_attempts(node_run_id)
    assert attempts[-1].status is AttemptStatus.FAILED
    node_run = await store.get_node_run(node_run_id)
    run = await store.get_run(run_id)
    assert node_run is not None and node_run.status is RunStatus.WAITING
    assert run is not None and run.status is RunStatus.WAITING


@pytest.mark.asyncio
async def test_runtime_deadline_persists_timed_out_attempt_and_parks_logical_state() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work: Any, _context: Any) -> None:
        await asyncio.sleep(0.1)

    with pytest.raises(RuntimeDeadlineExceeded):
        await service.execute(
            node_run_id,
            None,
            None,
            executor=executor,
            timeout_s=0.001,
        )

    attempts = await store.list_attempts(node_run_id)
    assert attempts[-1].status is AttemptStatus.TIMED_OUT
    assert attempts[-1].deadline_at is not None
    node_run = await store.get_node_run(node_run_id)
    run = await store.get_run(run_id)
    assert node_run is not None and node_run.status is RunStatus.WAITING
    assert run is not None and run.status is RunStatus.WAITING


@pytest.mark.asyncio
async def test_runtime_cancellation_persists_cancelled_attempt_without_phantom_running() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    started = asyncio.Event()

    async def executor(_work: Any, _context: Any) -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(service.execute(node_run_id, None, None, executor=executor))
    await started.wait()
    running = await store.list_attempts(node_run_id)
    attempt_id = running[-1].attempt_id

    assert await service.cancel(attempt_id) is True
    with pytest.raises(asyncio.CancelledError):
        await task

    attempts = await store.list_attempts(node_run_id)
    assert attempts[-1].status is AttemptStatus.CANCELLED
    node_run = await store.get_node_run(node_run_id)
    run = await store.get_run(run_id)
    # Terminal, not parked (#230). `service.cancel()` is a request to stop, so
    # the retry decision has been made and it was *don't*. Parked here — which
    # is what this asserted before — left a cancelled turn indistinguishable
    # from a provider outage on any record that counts them.
    assert node_run is not None and node_run.status is RunStatus.CANCELLED
    assert run is not None and run.status is RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_failed_attempt_can_retry_same_logical_node_run() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def fail(_work: Any, _context: Any) -> None:
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError, match="transient"):
        await service.execute(node_run_id, None, None, executor=fail)

    parked_node_run = await store.get_node_run(node_run_id)
    parked_run = await store.get_run(run_id)
    assert parked_node_run is not None and parked_node_run.status is RunStatus.WAITING
    assert parked_run is not None and parked_run.status is RunStatus.WAITING

    async def succeed(_work: Any, _context: Any) -> str:
        return "ok"

    second = await service.execute(node_run_id, None, None, executor=succeed)
    attempts = await store.list_attempts(node_run_id)

    assert [attempt.ordinal for attempt in attempts] == [1, 2]
    assert attempts[0].status is AttemptStatus.FAILED
    assert second.status is AttemptStatus.COMPLETED
    assert second.result == "ok"
    completed_node_run = await store.get_node_run(node_run_id)
    resumed_run = await store.get_run(run_id)
    assert completed_node_run is not None and completed_node_run.status is RunStatus.COMPLETED
    assert resumed_run is not None and resumed_run.status is RunStatus.COMPLETED
    assert resumed_run.result == "ok"


@pytest.mark.asyncio
async def test_a_yielded_attempt_is_a_pause_in_the_runtime_metrics_too() -> None:
    """The two records of one event agree (#642).

    `AttemptExecutionService` terminalizes the Attempt as YIELDED, and before
    this the same escape was counted as a failed execution in `RuntimeMetrics`,
    so the physical outcome and the migration-trigger measurement said different
    things about the same pause. This is the end-to-end version of the runtime
    unit tests: it goes through the class the consumer actually raises.
    """
    store, _run_id, node_run_id = await _node_run()
    runtime = PythonExecutionRuntime()
    service = AttemptExecutionService(store=store, runtime=runtime)

    async def pause(_work: Any, _context: Any) -> None:
        raise ExecutionYielded(awaits_human=True)

    terminal = await service.execute(node_run_id, None, None, executor=pause)

    assert terminal.status is AttemptStatus.YIELDED
    metrics = runtime.metrics()
    assert metrics.executions_yielded == 1
    assert metrics.executions_failed == 0
    assert metrics.executions_completed == 0
