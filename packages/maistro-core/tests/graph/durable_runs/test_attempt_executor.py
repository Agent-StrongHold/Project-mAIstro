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
from maistro.graph.nodes import (
    BaseNode,
    NodeContext,
    NodeResult,
    ReplaySemantics,
    compose_node,
    get_node,
)
from maistro.runs import Attempt, AttemptStatus, GraphSnapshot, NodeRun, Run
from maistro.runtime import PythonExecutionRuntime
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


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


class _UnboundEffect(BaseNode[_Empty, _Seed]):
    """An EFFECT_KEY node whose key builder explicitly reports no key.

    Distinct from a node with no ``logical_effect_key`` at all: the callable
    exists and runs, but the effect contract it returns is unusable, so the
    fold must still refuse a second visit.
    """

    kind: ClassVar[str] = "test.attempt.unbound_effect"
    kind_category: ClassVar[str] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Seed
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
    calls: ClassVar[int] = 0

    def logical_effect_key(self, inputs: _Empty, ctx: NodeContext) -> str | None:
        del inputs, ctx
        return None

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Seed:
        type(self).calls += 1
        raise RuntimeError("effect key unavailable")


class _HardNonRetryable(BaseNode[_Empty, _Seed]):
    kind: ClassVar[str] = "test.attempt.hard_non_retryable"
    kind_category: ClassVar[str] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Seed
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.NON_RETRYABLE
    calls: ClassVar[int] = 0

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Seed:
        type(self).calls += 1
        raise RuntimeError("ambiguous effect")


class _NeverRetry(BaseNode[_Empty, _Seed]):
    kind: ClassVar[str] = "test.attempt.never_retry"
    kind_category: ClassVar[str] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Seed
    # A label without a concrete key must fail closed rather than retrying an
    # ambiguous external effect.
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
    calls: ClassVar[int] = 0

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Seed:
        type(self).calls += 1
        raise RuntimeError("ambiguous effect")


def _unbound_effect_graph() -> Graph:
    return Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Unbound effect",
        nodes=[
            Node(
                node_id="unbound",
                node_type=_UnboundEffect.kind,
                policies={"max_attempts": 3},
            )
        ],
        metadata={"entry_node": "unbound"},
    )


def _hard_non_retryable_graph() -> Graph:
    return Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Hard non-retryable",
        nodes=[
            Node(
                node_id="hard",
                node_type=_HardNonRetryable.kind,
                policies={"max_attempts": 3},
            )
        ],
        metadata={"entry_node": "hard"},
    )


def _never_retry_graph() -> Graph:
    return Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Non-retryable",
        nodes=[
            Node(
                node_id="never",
                node_type=_NeverRetry.kind,
                policies={"max_attempts": 3},
            )
        ],
        metadata={"entry_node": "never"},
    )


def _remote_work_graph() -> Graph:
    """A graph whose only node is the production `agent.remote_work` kind."""
    return Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Delegated external work",
        nodes=[
            Node(
                node_id="remote",
                node_type="agent.remote_work",
                policies={"max_attempts": 3},
            )
        ],
        metadata={"entry_node": "remote"},
    )


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


def _unbound_effect_resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    del graph
    assert node_id == "unbound"
    return _UnboundEffect()


def _hard_non_retryable_resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    del graph
    assert node_id == "hard"
    return _HardNonRetryable()


def _never_retry_resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    del graph
    assert node_id == "never"
    return _NeverRetry()


def _remote_work_resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    """Resolve through the production registry, not a test double."""
    del graph
    assert node_id == "remote"
    return compose_node("agent.remote_work", {})


def _blocking_resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    del graph
    assert node_id == "blocking"
    return _Blocking()


def _single_recovery_record(
    *,
    attempt_status: AttemptStatus,
    attempt_result: object | None = None,
    node_id: str = "start",
) -> DurableRunRecord:
    kinds = {
        "start": _Start.kind,
        "never": _NeverRetry.kind,
        "hard": _HardNonRetryable.kind,
    }
    graph = Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Recovery",
        nodes=[Node(node_id=node_id, node_type=kinds[node_id])],
        metadata={"entry_node": node_id},
    )
    run = Run(
        run_id="recover-run",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.RUNNING,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    node_run = NodeRun(
        node_run_id="recover-node-run",
        run_id=run.run_id,
        node_id=node_id,
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
    state = GraphExecutionState(run_id=run.run_id, active_node_ids=(node_id,))
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
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
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
async def test_unkeyed_effect_contract_overrides_a_graph_retry_budget() -> None:
    """A node labeled EFFECT_KEY but exposing no key gets exactly one visit."""
    _NeverRetry.calls = 0
    store = InMemoryDurableRunStore()

    record = await run_durable_graph(
        _never_retry_graph(),
        store=store,
        node_resolver=_never_retry_resolver,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )

    assert record.status is RunStatus.FAILED
    assert _NeverRetry.calls == 1
    assert len(record.attempts) == 1


@pytest.mark.asyncio
async def test_effect_key_contract_requires_a_recorded_key_before_retry() -> None:
    """An explicit ``logical_effect_key -> None`` is as unusable as no method."""
    _UnboundEffect.calls = 0
    store = InMemoryDurableRunStore()

    record = await run_durable_graph(
        _unbound_effect_graph(),
        store=store,
        node_resolver=_unbound_effect_resolver,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )

    assert record.status is RunStatus.FAILED
    assert _UnboundEffect.calls == 1
    assert len(record.attempts) == 1


@pytest.mark.asyncio
async def test_non_retryable_contract_overrides_a_graph_retry_budget() -> None:
    _HardNonRetryable.calls = 0
    store = InMemoryDurableRunStore()

    record = await run_durable_graph(
        _hard_non_retryable_graph(),
        store=store,
        node_resolver=_hard_non_retryable_resolver,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )

    assert record.status is RunStatus.FAILED
    assert _HardNonRetryable.calls == 1
    assert len(record.attempts) == 1


@pytest.mark.asyncio
async def test_production_remote_work_kind_is_not_retried_under_a_retry_budget() -> None:
    """The shipped `agent.remote_work` kind declares NON_RETRYABLE (#1194).

    The work executes at an A2A peer, so a failed visit must never be
    re-dispatched locally: whether the remote effect already happened is not
    observable here, and the delegation recovery path owns reconciliation.
    This pins the *catalog* declaration to the executor's behaviour — the
    graph's `max_attempts` budget must not override it.
    """
    assert get_node("agent.remote_work").replay_semantics is ReplaySemantics.NON_RETRYABLE

    store = InMemoryDurableRunStore()

    record = await run_durable_graph(
        _remote_work_graph(),
        store=store,
        node_resolver=_remote_work_resolver,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )

    assert record.status is RunStatus.FAILED
    assert len(record.attempts) == 1
    assert record.graph_state.visit_counts.get("remote") == 1


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
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
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


class _RecordingSink:
    """Stands in for the canonical recovery Event sink (#62)."""

    def __init__(self) -> None:
        self.facts: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.facts.append(event)


@pytest.mark.asyncio
async def test_resume_reports_crash_dispositions_on_the_recovery_event_sink() -> None:
    """A resume that terminalizes process-lost physical work is a recovery
    disposition (#462), so it must reach the same canonical Event stream the
    abandoned-Attempt sweep reports on -- not silently persist and return
    (#62)."""
    from maistro.runs.recovery_events import RECOVERY_EVENT_TYPE

    _Start.calls = 0
    store = InMemoryDurableRunStore()
    await store.create(_single_recovery_record(attempt_status=AttemptStatus.RUNNING))
    sink = _RecordingSink()

    record = await resume_durable_graph(
        "recover-run", store=store, node_resolver=_resolver, events=sink
    )

    assert record.status is RunStatus.COMPLETED
    assert len(sink.facts) == 1
    fact = sink.facts[0]
    assert fact.attempt_id == "recover-attempt"
    assert fact.disposition == "recovered_and_parked"
    assert fact.cancellation_cause == "recovered"
    legacy = fact.to_legacy_event()
    assert legacy.event_type == RECOVERY_EVENT_TYPE
    assert legacy.correlation_id == "recover-run"


@pytest.mark.asyncio
async def test_resume_without_a_sink_behaves_exactly_as_before() -> None:
    """The sink is observability, not execution: a caller with no listener
    still resumes, because refusing to recover work because nothing is
    listening would invert the dependency."""
    _Start.calls = 0
    store = InMemoryDurableRunStore()
    await store.create(_single_recovery_record(attempt_status=AttemptStatus.RUNNING))

    record = await resume_durable_graph("recover-run", store=store, node_resolver=_resolver)

    assert record.status is RunStatus.COMPLETED
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


@pytest.mark.asyncio
async def test_resume_never_reexecutes_a_non_retryable_nodes_ambiguous_effect() -> None:
    """Recovery re-dispatch consumes the executable replay contract (#1194).

    ADR-082826-08f0's orphan row still rotates the interrupted Attempt to a
    fresh chronological one, but for NON_RETRYABLE work the fresh Attempt
    records a refusal as its own evidence instead of invoking the node body:
    the effect may already have happened before the process died, and a second
    physical try is exactly the duplication the contract forbids. The fold's
    exhausted-failure rule (which reads the same contract) fails the Run, so
    the ambiguity lands in front of a person instead of on the remote system.
    """
    # One call before the crash: the physical effect's outcome is unknown.
    _HardNonRetryable.calls = 1
    store = InMemoryDurableRunStore()
    await store.create(
        _single_recovery_record(attempt_status=AttemptStatus.RUNNING, node_id="hard")
    )

    record = await resume_durable_graph(
        "recover-run", store=store, node_resolver=_hard_non_retryable_resolver
    )

    # The body never ran again: one ambiguous effect, not two.
    assert _HardNonRetryable.calls == 1
    # The canonical recovery rotation still happened (ADR-082826-08f0): the
    # orphaned Attempt is CANCELLED and a fresh chronological Attempt settles
    # the refusal as its own durable evidence.
    assert [attempt.status for attempt in record.attempts] == [
        AttemptStatus.CANCELLED,
        AttemptStatus.COMPLETED,
    ]
    assert "ReplayRefused" in str(record.attempts[1].result)
    # The fold fails the Run with the refusal, naming the contract.
    assert record.status is RunStatus.FAILED
    assert (record.run.error or "").startswith("ReplayRefused:")
    assert record.node_runs[0].status is RunStatus.FAILED


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
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        ),
        graph_state=GraphExecutionState(run_id="redispatch-run"),
        version=1,
    )
    paused = NodeResult(success=True, status="paused", resume_at=resume_at)

    assert (
        attempt_executor._requires_continuation_redispatch(record, "wait-step", paused) is expected
    )
