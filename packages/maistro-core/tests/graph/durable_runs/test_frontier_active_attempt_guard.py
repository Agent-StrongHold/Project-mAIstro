"""The walker leaves a Run to its live Attempt when the terminal write fails (#1151).

A node whose runtime work already ran can still fail to persist its terminal
Attempt write (the #1288 contract: the write is never retried in-line; the
chat path surfaces `ChatDispatchUnrecorded` and leaves the Attempt RUNNING
for the recovery sweep). When that failure surfaces through the durable
Graph walker, `attempt_executor._frontier_has_active_attempt` keeps both the
frontier exception handler and the post-mirror loop check from
terminalizing the Run: a FAILED Run holding a RUNNING, leased Attempt would
be exactly the contradictory Run #1151's acceptance forbids, and the
fabricated `PhysicalExecutionError` would pre-empt the outcome the bounded
recovery sweep must own (observe terminal evidence, or reclaim the lapsed
lease per ADR-082526-b36a and park the Run for its retry policy).

Fail-before: with the guard predicate disabled, this walk marks the Run
FAILED (`PhysicalExecutionError`) while its Attempt is still RUNNING under a
live lease.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.container import create_container
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    run_durable_graph,
)
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.runs.lifecycle import lease_is_expired
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.types.config import AgentConfig

_WORKSPACE = "ws-frontier-active-attempt-guard"


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _Step(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.frontier_guard.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        return _Out()


class _TerminalWriteLost(Exception):
    """A plain `Exception`: the walker survives; only the write failed."""


class _LostTerminalWriteRunStore:
    """A RunStore whose `transition_attempt` to COMPLETED always fails.

    Every other operation passes through untouched, so the Run/NodeRun
    lifecycle mirror and a later lease reclaim still reach the real store.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        operation = getattr(self._inner, name)
        if name != "transition_attempt":
            return operation

        async def call(attempt_id: str, target: AttemptStatus, **kwargs: Any) -> Any:
            if target is not AttemptStatus.COMPLETED:
                return await operation(attempt_id, target, **kwargs)
            raise _TerminalWriteLost("terminal completion write lost")

        return call


async def test_terminal_write_failure_leaves_the_run_to_its_live_attempt() -> None:
    container = await create_container(AgentConfig(router_api_key="test-key"))
    run_store = container.run_store
    root = await container.project_scope_store.create_root(_WORKSPACE)
    graph = Graph(
        workspace_id=_WORKSPACE,
        project_id=root.project_id,
        name="terminal write lost",
        nodes=[Node(node_id="step", node_type=_Step.kind)],
    )
    admitted = await run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    walker_store = _LostTerminalWriteRunStore(run_store)

    record = await run_durable_graph(
        graph,
        store=CanonicalDurableRunStore(walker_store, InMemoryGraphContinuationStore()),
        node_resolver=lambda _node_id, _graph: _Step(),
        run_id=admitted.run_id,
        run_store=walker_store,
    )

    # The losing caller must not terminalize work a live Attempt still owns.
    assert record.run.status is RunStatus.RUNNING
    run = await run_store.get_run(admitted.run_id)
    assert run is not None and run.status is RunStatus.RUNNING
    assert run.error is None
    (node_run,) = await run_store.list_node_runs(admitted.run_id)
    assert node_run.status is RunStatus.RUNNING
    (attempt,) = await run_store.list_attempts(node_run.node_run_id)
    assert attempt.status is AttemptStatus.RUNNING
    assert not lease_is_expired(attempt, datetime.now(UTC))

    # The bounded recovery sweep owns the outcome: past the lapsed lease the
    # Attempt is reclaimed and the Run is parked for its retry policy — never
    # FAILED by the walker that lost the write.
    moment = datetime.now(UTC) + timedelta(hours=1)
    await container.recover_abandoned_attempts(now=moment)

    (reclaimed,) = await run_store.list_attempts(node_run.node_run_id)
    assert reclaimed.status is AttemptStatus.CANCELLED
    parked_node_run = await run_store.get_node_run(node_run.node_run_id)
    assert parked_node_run is not None and parked_node_run.status is RunStatus.WAITING
    parked_run = await run_store.get_run(admitted.run_id)
    assert parked_run is not None and parked_run.status is RunStatus.WAITING
