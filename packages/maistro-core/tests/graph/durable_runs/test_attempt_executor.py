from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Edge, Graph, GraphExecutionState, Node
from maistro.graph.durable_runs import (
    DurableRunRecord,
    InMemoryDurableRunStore,
    RunStatus,
    attempt_executor,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.nodes import BaseNode, NodeContext, NodeResult
from maistro.runs import Attempt, AttemptStatus, GraphSnapshot, NodeRun, Run
from maistro.runtime import PythonExecutionRuntime


class _Empty(BaseModel):
    pass


class _Seed(BaseModel):
    seed: str


class _BranchOut(BaseModel):
    branch: str


class _Start(BaseNode[_Empty, _Seed]):
    kind: ClassVar[str] = "test.attempt.start"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Seed
    calls: ClassVar[int] = 0

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Seed:
        type(self).calls += 1
        return _Seed(seed="go")


class _Barrier:
    started: ClassVar[int] = 0
    ready: ClassVar[asyncio.Event | None] = None

    @classmethod
    def reset(cls) -> None:
        cls.started = 0
        cls.ready = asyncio.Event()

    @classmethod
    async def arrive(cls) -> None:
        assert cls.ready is not None
        cls.started += 1
        if cls.started == 2:
            cls.ready.set()
        await asyncio.wait_for(cls.ready.wait(), timeout=1.0)


class _Left(BaseNode[_Empty, _BranchOut]):
    kind: ClassVar[str] = "test.attempt.left"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _BranchOut

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _BranchOut:
        await _Barrier.arrive()
        return _BranchOut(branch="left")


class _Right(BaseNode[_Empty, _BranchOut]):
    kind: ClassVar[str] = "test.attempt.right"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _BranchOut

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _BranchOut:
        await _Barrier.arrive()
        return _BranchOut(branch="right")


class _Blocking(BaseNode[_Empty, _Seed]):
    kind: ClassVar[str] = "test.attempt.blocking"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Seed
    started: ClassVar[asyncio.Event | None] = None

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Seed:
        assert self.started is not None
        self.started.set()
        await asyncio.Event().wait()
        return _Seed(seed="unreachable")


class _RecordingRuntime(PythonExecutionRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.execution_ids: list[str] = []

    async def execute(
        self,
        work_item: Any,
        execution_context: Any,
        *,
        execution_id: str,
        executor: Any,
        timeout_s: float | None = None,
    ) -> Any:
        self.execution_ids.append(execution_id)
        return await super().execute(
            work_item,
            execution_context,
            execution_id=execution_id,
            executor=executor,
            timeout_s=timeout_s,
        )


def _graph() -> Graph:
    return Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Attempt frontier",
        nodes=[
            Node(node_id="start", node_type=_Start.kind),
            Node(node_id="left", node_type=_Left.kind),
            Node(node_id="right", node_type=_Right.kind),
        ],
        edges=[
            Edge(edge_id="start-left", from_node="start", to_node="left"),
            Edge(
                edge_id="start-right",
                from_node="start",
                to_node="right",
                metadata={"parallel": True},
            ),
        ],
        metadata={"entry_node": "start"},
    )


def _resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    del graph
    return {"start": _Start, "left": _Left, "right": _Right}[node_id]()


def _blocking_graph() -> Graph:
    return Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Cancelled Attempt",
        nodes=[Node(node_id="blocking", node_type=_Blocking.kind)],
        metadata={"entry_node": "blocking"},
    )


def _blocking_resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    del graph
    assert node_id == "blocking"
    return _Blocking()


def _single_recovery_record(
    *, attempt_status: AttemptStatus, attempt_result: object | None = None
) -> DurableRunRecord:
    graph = Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Recovery",
        nodes=[Node(node_id="start", node_type=_Start.kind)],
        metadata={"entry_node": "start"},
    )
    run = Run(
        run_id="recover-run",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.RUNNING,
    )
    node_run = NodeRun(
        node_run_id="recover-node-run",
        run_id=run.run_id,
        node_id="start",
        ordinal=1,
        status=RunStatus.RUNNING,
    )
    values: dict[str, object] = {
        "attempt_id": "recover-attempt",
        "node_run_id": node_run.node_run_id,
        "ordinal": 1,
        "status": attempt_status,
    }
    if attempt_status is AttemptStatus.RUNNING:
        values["started_at"] = run.created_at
    if attempt_status in {
        AttemptStatus.COMPLETED,
        AttemptStatus.FAILED,
        AttemptStatus.CANCELLED,
        AttemptStatus.TIMED_OUT,
    }:
        values["started_at"] = run.created_at
        values["finished_at"] = run.created_at
        values["result"] = attempt_result
    attempt = Attempt.model_validate(values)
    state = GraphExecutionState(run_id=run.run_id, active_node_ids=("start",))
    return DurableRunRecord(
        run=run,
        graph_state=state,
        node_runs=(node_run,),
        attempts=(attempt,),
        version=1,
    )


@pytest.mark.asyncio
async def test_public_durable_executor_routes_each_node_run_through_attempt_runtime() -> None:
    _Barrier.reset()
    store = InMemoryDurableRunStore()
    runtime = _RecordingRuntime()

    record = await run_durable_graph(
        _graph(),
        store=store,
        node_resolver=_resolver,
        runtime=runtime,
    )

    assert record.status is RunStatus.COMPLETED
    assert _Barrier.started == 2
    assert [node_run.node_id for node_run in record.node_runs] == [
        "start",
        "left",
        "right",
    ]
    assert len(record.attempts) == 3
    assert [attempt.ordinal for attempt in record.attempts] == [1, 1, 1]
    assert all(attempt.status is AttemptStatus.COMPLETED for attempt in record.attempts)
    assert {attempt.node_run_id for attempt in record.attempts} == {
        node_run.node_run_id for node_run in record.node_runs
    }
    assert set(runtime.execution_ids) == {attempt.attempt_id for attempt in record.attempts}


@pytest.mark.asyncio
async def test_outer_cancellation_terminalizes_attempt_node_run_and_run() -> None:
    _Blocking.started = asyncio.Event()
    store = InMemoryDurableRunStore()
    task = asyncio.create_task(
        run_durable_graph(
            _blocking_graph(),
            store=store,
            node_resolver=_blocking_resolver,
            run_id="cancel-run",
        )
    )

    await asyncio.wait_for(_Blocking.started.wait(), timeout=1.0)
    in_flight = await store.get("cancel-run")
    assert in_flight is not None
    assert in_flight.node_runs[0].status is RunStatus.RUNNING
    assert in_flight.attempts[0].status is AttemptStatus.RUNNING

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    persisted = await store.get("cancel-run")
    assert persisted is not None
    assert persisted.status is RunStatus.CANCELLED
    assert persisted.node_runs[0].status is RunStatus.CANCELLED
    assert persisted.attempts[0].status is AttemptStatus.CANCELLED
    # The node names what actually ended it: its own Attempt was cancelled, so
    # the reconciler terminalizes it directly (#230) and the error is the
    # Attempt's. Before #230 it reached this state only by being swept up in the
    # Run's cascade, which reported the Run's terminalization rather than the
    # cancellation that caused it — true, but one remove from the cause.
    assert persisted.node_runs[0].error == "execution cancelled"


@pytest.mark.asyncio
async def test_resume_cancels_orphaned_active_attempt_then_creates_recovery_attempt() -> None:
    _Start.calls = 0
    store = InMemoryDurableRunStore()
    await store.create(_single_recovery_record(attempt_status=AttemptStatus.RUNNING))

    record = await resume_durable_graph("recover-run", store=store, node_resolver=_resolver)

    assert record.status is RunStatus.COMPLETED
    assert [attempt.status for attempt in record.attempts] == [
        AttemptStatus.CANCELLED,
        AttemptStatus.COMPLETED,
    ]
    assert [attempt.ordinal for attempt in record.attempts] == [1, 2]
    assert _Start.calls == 1


@pytest.mark.asyncio
async def test_resume_folds_completed_attempt_without_redispatching_node() -> None:
    _Start.calls = 0
    persisted_result = NodeResult(success=True, output={"seed": "already-done"})
    store = InMemoryDurableRunStore()
    await store.create(
        _single_recovery_record(
            attempt_status=AttemptStatus.COMPLETED,
            attempt_result=persisted_result,
        )
    )

    record = await resume_durable_graph("recover-run", store=store, node_resolver=_resolver)

    assert record.status is RunStatus.COMPLETED
    assert len(record.attempts) == 1
    assert record.attempts[0].status is AttemptStatus.COMPLETED
    assert record.node_runs[0].result == {"seed": "already-done"}
    assert _Start.calls == 0


@pytest.mark.parametrize(
    ("resume_at", "expected"),
    [
        (datetime.now(UTC) - timedelta(seconds=1), True),
        (datetime.now(UTC) + timedelta(hours=1), False),
        (None, False),
    ],
)
async def test_a_timed_pause_needs_a_fresh_try_only_once_its_deadline_elapses(
    resume_at: datetime | None, expected: bool
) -> None:
    """A paused node that is not waiting on a human is waiting on the clock:
    the persisted pause is only evidence of work to redo once it is due."""
    record = DurableRunRecord(
        run=Run(
            run_id="redispatch-run",
            workspace_id="ws-1",
            project_id="project-1",
            graph=GraphSnapshot.from_graph(
                Graph(
                    workspace_id="ws-1",
                    project_id="project-1",
                    name="redispatch",
                    nodes=[Node(node_id="wait-step", node_type="test.attempt.wait")],
                )
            ),
            status=RunStatus.WAITING,
        ),
        graph_state=GraphExecutionState(run_id="redispatch-run"),
        version=1,
    )
    paused = NodeResult(success=True, status="paused", resume_at=resume_at)

    assert (
        attempt_executor._requires_continuation_redispatch(record, "wait-step", paused) is expected
    )
