"""Crash-window invariants on the execution spine (P0.7, AC-P7, #804).

AC-P7: a process killed at any of the named points leaves a Run that the next
recovery tick settles or resumes; no Run is RUNNING with no live Attempt after
one tick. Each case below kills the process at one two-write seam, restarts
recovery in a fresh store object over the same durable state, runs exactly one
tick of the recovery cadence Hive schedules (`canonical_recovery` plus
`dag_recovery`), and reads the Run back.

Builds on the kill-recovery evidence pack (#1611, `test_recovery_evidence_pack`):
the same canonical seams, no second recovery authority. The kill is forced at a
named store write rather than hoped for, the forced-interleaving discipline of
`tests/workspaces/test_workspace_store_conformance.py`, and it is a
`BaseException` so no executor boundary can absorb it and write a disposition a
real SIGKILL never would.

A window still open is listed in `KNOWN_GAPS`, and its test asserts the Run is
still stranded after one tick. Closing a window fails its test until the entry
is deleted.

Async tests follow the suite's auto mode. Do not add pytest.mark.asyncio.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

import pytest
from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Edge, Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    recover_queued_graph_runs,
    resume_due_graph_runs,
    run_durable_graph,
)
from maistro.graph.durable_runs.canonical_store import TERMINAL_SETTLE_QUIET_PERIOD
from maistro.graph.durable_runs.continuation import GraphContinuation, GraphContinuationStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.runs.execution import AttemptExecutionService, AttemptExecutionStore
from maistro.runs.lifecycle import lease_is_expired
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    AttemptStatus,
    RunStatus,
)
from maistro.runs.store import RunStore
from maistro.runtime import PythonExecutionRuntime
from maistro.testing.runs import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.types.config import AgentConfig

WINDOWS = frozenset(
    {
        "settle_after_last_node_run",
        "frontier_node_runs_after_resume_at_cleared",
        "attempt_completion_write_lost",
        "attempt_completion_before_reconcile",
        "terminal_continuation_before_mirror",
    }
)

KNOWN_GAPS = frozenset()

_WORKSPACE = "ws-crash-windows"
_LEASE_TTL = timedelta(seconds=30)
#: How long after the crash the restarted process ticks: past every lease,
#: resume claim and terminal quiet period the spine uses.
_RESTART_DELAY = timedelta(hours=1)


class _ProcessKilled(BaseException):
    """Not an `Exception`, so no executor boundary can absorb the crash."""


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _Step(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.crash_window_invariants.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        return _Out()


class _KillAt:
    """A RunStore whose process dies at one named write.

    ``before`` kills instead of the write; otherwise the write commits and the
    process dies before anything after it runs.
    """

    def __init__(
        self,
        inner: RunStore,
        method: str,
        when: Callable[..., bool],
        *,
        before: bool,
    ) -> None:
        self._inner = inner
        self._method = method
        self._when = when
        self._before = before

    def __getattr__(self, name: str) -> Any:
        operation = getattr(self._inner, name)
        if name != self._method:
            return operation

        async def call(*args: Any, **kwargs: Any) -> Any:
            if not self._when(*args, **kwargs):
                return await operation(*args, **kwargs)
            if self._before:
                raise _ProcessKilled
            await operation(*args, **kwargs)
            raise _ProcessKilled

        return call


class _RestartedStore(CanonicalDurableRunStore):
    """The restarted process's durable store, read at the tick's moment.

    `recover_queued_graph_runs` takes no clock and reconciles at the wall
    clock, while `resume_due_graph_runs` reconciles at the ``now`` it is
    given. Pinning both to one moment makes the tick one instant in the
    restarted process rather than two readings an hour apart.
    """

    tick_moment: datetime | None = None

    async def reconcile_persistence(self, *, limit: int = 100, now: datetime | None = None) -> int:
        return await super().reconcile_persistence(limit=limit, now=now or self.tick_moment)


class _KillingWalker(CanonicalDurableRunStore):
    """The walker's durable store, whose process dies at one checkpoint.

    ``continuation_lands`` writes the continuation half of the checkpoint
    before the kill, so only its canonical mirror is lost.
    """

    def __init__(self, run_store: RunStore, continuations: GraphContinuationStore) -> None:
        super().__init__(run_store, continuations)
        self._continuation_store = continuations
        self.kill_on: Callable[[DurableRunRecord], bool] = lambda _record: False
        self.continuation_lands = False

    async def update(self, record: DurableRunRecord) -> DurableRunRecord:
        if not self.kill_on(record):
            return await super().update(record)
        if self.continuation_lands:
            await self._continuation_store.update(GraphContinuation.of(record))
        raise _ProcessKilled


class _Spine:
    """One Container's RunStore and Graph continuations, shared by both processes."""

    def __init__(self, container: Container, project_id: str) -> None:
        self.container = container
        self.run_store = container.run_store
        self.project_id = project_id
        self.continuations = InMemoryGraphContinuationStore()
        self.walker = _KillingWalker(self.run_store, self.continuations)
        self._recovery: _RestartedStore | None = None

    def graph(self, *, chained: bool = False) -> Graph:
        nodes = [Node(node_id="a", node_type=_Step.kind)]
        edges: list[Edge] = []
        if chained:
            nodes.append(Node(node_id="b", node_type=_Step.kind))
            edges.append(Edge(edge_id="a-b", from_node="a", to_node="b"))
        return Graph(
            workspace_id=_WORKSPACE,
            project_id=self.project_id,
            name="crash window",
            nodes=nodes,
            edges=edges,
        )

    async def tick(self, moment: datetime) -> None:
        """One tick of every recovery half Hive schedules, at one moment.

        `canonical_recovery`'s three Container halves, then `dag_recovery`'s
        queued and due Graph halves, in the restarted process.
        """
        if self._recovery is None:
            self._recovery = _RestartedStore(self.run_store, self.continuations)
        recovery = self._recovery
        recovery.tick_moment = moment
        await self.container.recover_abandoned_attempts(now=moment)
        await self.container.recover_stranded_chat_admissions(now=moment)
        await self.container.resume_parked_runs(now=moment)

        def resolver(_run: Any) -> Any:
            return lambda _node_id, _graph: _Step()

        await recover_queued_graph_runs(
            store=recovery,
            run_store=self.run_store,
            node_resolver_factory=resolver,
            eligible=lambda _run: True,
        )
        await resume_due_graph_runs(
            store=recovery,
            run_store=self.run_store,
            node_resolver_factory=resolver,
            now=moment,
        )


async def _spine() -> _Spine:
    container = await create_container(AgentConfig(router_api_key="test-key"))
    root = await container.project_scope_store.create_root(_WORKSPACE)
    return _Spine(container, root.project_id)


async def _stranded(store: RunStore, run_id: str, moment: datetime) -> bool:
    """RUNNING with no live Attempt: the state AC-P7 forbids after one tick."""
    run = await store.get_run(run_id)
    assert run is not None
    if run.status is not RunStatus.RUNNING:
        return False
    for node_run in await store.list_node_runs(run_id):
        for attempt in await store.list_attempts(node_run.node_run_id):
            if attempt.status not in TERMINAL_ATTEMPT_STATUSES and not lease_is_expired(
                attempt, moment
            ):
                return False
    return True


async def _assert_after_one_tick(spine: _Spine, window: str, run_id: str) -> datetime:
    moment = datetime.now(UTC) + _RESTART_DELAY
    await spine.tick(moment)
    stranded = await _stranded(spine.run_store, run_id, moment)
    if window in KNOWN_GAPS:
        assert stranded, f"{window} no longer strands its Run; delete it from KNOWN_GAPS"
    else:
        assert not stranded, f"{window} left its Run RUNNING with no live Attempt"
    return moment


async def _admitted_attempt_service(
    spine: _Spine, kill: _KillAt
) -> tuple[AttemptExecutionService, str, str]:
    """A RUNNING Run and NodeRun, as admission claims them (#251), and a leased executor."""
    run = await spine.run_store.create_run(
        spine.graph(),
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    await spine.run_store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await spine.run_store.create_node_run(run.run_id, node_id="a")
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await spine.run_store.transition_node_run(node_run.node_run_id, status)
    service = AttemptExecutionService(
        store=cast(AttemptExecutionStore, kill),
        runtime=PythonExecutionRuntime(),
        lease_ttl=_LEASE_TTL,
    )
    return service, run.run_id, node_run.node_run_id


async def _succeed(_work_item: Any, _context: Any) -> dict[str, str]:
    return {"text": "done"}


async def _kill_attempt_execution(spine: _Spine, kill: _KillAt) -> str:
    """Drive one successful Attempt through `AttemptExecutionService` into the kill."""
    service, run_id, node_run_id = await _admitted_attempt_service(spine, kill)
    with pytest.raises(_ProcessKilled):
        await service.execute(node_run_id, {}, None, executor=_succeed, executor_id="worker-1")
    return run_id


async def _kill_graph_walk(spine: _Spine, graph: Graph, run_id: str) -> None:
    """Drive an admitted durable Graph through the canonical walker into the kill."""
    with pytest.raises(_ProcessKilled):
        await run_durable_graph(
            graph,
            store=spine.walker,
            node_resolver=lambda _node_id, _graph: _Step(),
            run_id=run_id,
            run_store=spine.run_store,
        )


def test_every_known_gap_names_a_window() -> None:
    assert KNOWN_GAPS <= WINDOWS


async def test_run_settlement_lost_after_the_last_node_run_commits() -> None:
    """`runs/reconciliation.py`: the NodeRun accepts its outcome, the Run never settles.

    The reconciler replays settlement for an already-accepted Attempt, but only
    when something reconciles that Attempt again. The lease sweep reclaims open
    Attempts only, and this one is COMPLETED.
    """
    spine = await _spine()

    def run_terminal(_run_id: str, target: RunStatus, **_kw: Any) -> bool:
        return target in TERMINAL_RUN_STATUSES

    run_id = await _kill_attempt_execution(
        spine, _KillAt(spine.run_store, "transition_run", run_terminal, before=True)
    )
    (node_run,) = await spine.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.COMPLETED
    assert node_run.accepted_outcome is not None

    await _assert_after_one_tick(spine, "settle_after_last_node_run", run_id)


async def test_attempt_completion_write_lost_before_it_commits() -> None:
    """`runs/execution.py`: the process dies at the success write, before it lands.

    The Attempt is still RUNNING under a lease nobody renews, so the lease
    sweep reclaims it and parks the Run (ADR-082526-b36a, #462).
    """
    spine = await _spine()

    def completes(_attempt_id: str, target: AttemptStatus, **_kw: Any) -> bool:
        return target is AttemptStatus.COMPLETED

    run_id = await _kill_attempt_execution(
        spine, _KillAt(spine.run_store, "transition_attempt", completes, before=True)
    )

    await _assert_after_one_tick(spine, "attempt_completion_write_lost", run_id)
    run = await spine.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.WAITING


async def test_attempt_completion_committed_before_reconciliation() -> None:
    """`runs/execution.py`: the success write lands outside the try, reconciliation never runs.

    The Attempt is COMPLETED, so no lease is left to lapse, while its NodeRun
    and Run still read RUNNING.
    """
    spine = await _spine()

    def completes(_attempt_id: str, target: AttemptStatus, **_kw: Any) -> bool:
        return target is AttemptStatus.COMPLETED

    run_id = await _kill_attempt_execution(
        spine, _KillAt(spine.run_store, "transition_attempt", completes, before=False)
    )
    (node_run,) = await spine.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.RUNNING
    (attempt,) = await spine.run_store.list_attempts(node_run.node_run_id)
    assert attempt.status is AttemptStatus.COMPLETED

    await _assert_after_one_tick(spine, "attempt_completion_before_reconcile", run_id)


async def test_frontier_node_runs_lost_after_the_checkpoint_cleared_resume_at() -> None:
    """`attempt_executor.py`: the next frontier's NodeRun exists, its checkpoint does not.

    The advancement checkpoint for ``a`` cleared ``resume_at``. The process
    dies inside `_ensure_frontier_node_runs` for ``b``, after the canonical
    NodeRun is minted and before the continuation records it, so the
    continuation reads RUNNING with no claim the due index would list.
    """
    spine = await _spine()
    graph = spine.graph(chained=True)
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    spine.walker.kill_on = lambda record: any(item.node_id == "b" for item in record.node_runs)

    await _kill_graph_walk(spine, graph, admitted.run_id)
    continuation = await spine.continuations.get(admitted.run_id)
    assert continuation is not None
    assert continuation.status is RunStatus.RUNNING
    assert continuation.resume_at is None
    node_runs = await spine.run_store.list_node_runs(admitted.run_id)
    assert {node_run.node_id for node_run in node_runs} == {"a", "b"}

    await _assert_after_one_tick(
        spine, "frontier_node_runs_after_resume_at_cleared", admitted.run_id
    )


async def test_terminal_continuation_written_before_its_canonical_mirror() -> None:
    """`canonical_store.py`: the continuation is terminal, the canonical Run is RUNNING.

    #1151 taught `_reconcile_run` to settle this, but only once one recovery
    process has watched the same terminal version for the quiet period, and a
    restarted process has watched nothing. The first tick only starts the
    clock, so the Run is stranded after one tick and settled on a later one.
    """
    spine = await _spine()
    graph = spine.graph()
    admitted = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    spine.walker.kill_on = lambda record: record.run.status in TERMINAL_RUN_STATUSES
    spine.walker.continuation_lands = True

    await _kill_graph_walk(spine, graph, admitted.run_id)
    continuation = await spine.continuations.get(admitted.run_id)
    assert continuation is not None and continuation.status is RunStatus.COMPLETED

    moment = await _assert_after_one_tick(
        spine, "terminal_continuation_before_mirror", admitted.run_id
    )

    await spine.tick(moment + TERMINAL_SETTLE_QUIET_PERIOD)
    settled = await spine.run_store.get_run(admitted.run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED
