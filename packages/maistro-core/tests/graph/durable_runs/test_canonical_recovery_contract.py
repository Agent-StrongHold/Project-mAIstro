"""Crash/retry contract for canonical durable Graph convergence (#44).

These tests cover the seams that matter once RunStore is the sole execution
system of record. A traversal checkpoint may lag a canonical write, but retry
must never create a second physical identity, execute a Graph under an
unrelated pinned Run, or wait for a global sweep to repair one Run's lease.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import executor as traversal
from maistro.graph.durable_runs.execution_store import DurableRunExecutionStore
from maistro.graph.durable_runs.stores import InMemoryDurableRunStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore, RunStatus
from maistro.runs.store import RunIntegrityError


class _StepIn(BaseModel):
    pass


class _StepOut(BaseModel):
    text: str = "done"


class _Step(BaseNode[_StepIn, _StepOut]):
    kind: ClassVar[str] = "test.canonical_recovery.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        return _StepOut()


class _ObserveRunStatus(BaseNode[_StepIn, _StepOut]):
    kind: ClassVar[str] = "test.canonical_recovery.observe_status"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    def __init__(self, run_store: InMemoryRunStore, run_id: str, seen: list[RunStatus]) -> None:
        self._run_store = run_store
        self._run_id = run_id
        self._seen = seen

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        run = await self._run_store.get_run(self._run_id)
        assert run is not None
        self._seen.append(run.status)
        return _StepOut()


class _FailNextUpdateStore(InMemoryDurableRunStore):
    """Inject one crash-shaped failure at the traversal checkpoint boundary."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_updates = 0

    async def update(self, record: DurableRunRecord) -> DurableRunRecord:
        if self.fail_updates:
            self.fail_updates -= 1
            raise RuntimeError("injected checkpoint failure")
        return await super().update(record)


class _FailCreateStore(InMemoryDurableRunStore):
    async def create(self, record: DurableRunRecord) -> DurableRunRecord:
        raise RuntimeError("injected initial checkpoint failure")


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-recovery")
    project = await projects.create(
        workspace_id="ws-recovery",
        parent_project_id=root.project_id,
        name="Recovery",
    )
    return InMemoryRunStore(project_store=projects), "ws-recovery", project.project_id


def _graph(workspace_id: str, project_id: str, *, name: str = "canonical") -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name=name,
        nodes=[Node(node_id="step", node_type=_Step.kind)],
    )


async def _bound_execution_store() -> tuple[
    InMemoryDurableRunStore,
    InMemoryRunStore,
    DurableRunExecutionStore,
    DurableRunRecord,
    str,
]:
    run_store, workspace_id, project_id = await _spine()
    graph = _graph(workspace_id, project_id)
    run = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    run = await run_store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await run_store.create_node_run(run.run_id, node_id="step")
    await run_store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    record = DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("step",)),
        node_runs=(node_run,),
        version=1,
    )
    store = InMemoryDurableRunStore()
    await store.create(record)
    return (
        store,
        run_store,
        DurableRunExecutionStore(store, run_id=run.run_id, run_store=run_store),
        record,
        node_run.node_run_id,
    )


async def test_pinned_run_rejects_a_different_graph_before_physical_work() -> None:
    """A run_id is an authority binding, not permission to reuse an identity."""
    run_store, workspace_id, project_id = await _spine()
    canonical_graph = _graph(workspace_id, project_id, name="canonical graph")
    supplied_graph = _graph(workspace_id, project_id, name="different graph")
    admitted = await run_store.create_run(canonical_graph, initial_status=RunStatus.QUEUED)
    executed: list[str] = []

    def resolver(node_id: str, graph: Any) -> _Step:
        executed.append(node_id)
        return _Step()

    with pytest.raises(RunIntegrityError, match=r"Graph|graph|pinned|Run"):
        await traversal.run_durable_graph(
            supplied_graph,
            store=InMemoryDurableRunStore(),
            node_resolver=resolver,
            run_id=admitted.run_id,
            run_store=run_store,
        )

    assert executed == []
    unchanged = await run_store.get_run(admitted.run_id)
    assert unchanged is not None and unchanged.status is RunStatus.QUEUED


async def test_pinned_parent_is_running_before_any_node_executes() -> None:
    """Physical work cannot run while its canonical parent still says QUEUED."""
    run_store, workspace_id, project_id = await _spine()
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="observe parent",
        nodes=[Node(node_id="step", node_type=_ObserveRunStatus.kind)],
    )
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    seen: list[RunStatus] = []

    record = await traversal.run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda node_id, graph: _ObserveRunStatus(run_store, admitted.run_id, seen),
        run_id=admitted.run_id,
        run_store=run_store,
    )

    assert record.status is RunStatus.COMPLETED
    assert seen == [RunStatus.RUNNING]


async def test_canonical_path_does_not_bootstrap_run_before_traversal_checkpoint() -> None:
    """Creating the Run first leaves an unrecoverable orphan if checkpointing dies.

    The canonical path therefore consumes an already-admitted Run. Admission is
    the durable operation that owns Run identity; traversal must not create a
    second cross-store bootstrap transaction of its own.
    """
    run_store, workspace_id, project_id = await _spine()

    with pytest.raises(RunIntegrityError, match=r"admit|run_id|Run"):
        await traversal.run_durable_graph(
            _graph(workspace_id, project_id),
            store=_FailCreateStore(),
            node_resolver=lambda node_id, graph: _Step(),
            run_store=run_store,
        )

    assert await run_store.list_by_status(RunStatus.CREATED, limit=10) == []
    assert await run_store.list_by_status(RunStatus.QUEUED, limit=10) == []
    assert await run_store.list_by_status(RunStatus.RUNNING, limit=10) == []


async def test_retry_adopts_node_run_created_before_checkpoint_failure() -> None:
    """Canonical NodeRun identity survives a failed aggregate checkpoint exactly once."""
    run_store, workspace_id, project_id = await _spine()
    graph = _graph(workspace_id, project_id)
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    store = _FailNextUpdateStore()
    store.fail_updates = 1

    with pytest.raises(RuntimeError, match="injected checkpoint failure"):
        await traversal.run_durable_graph(
            graph,
            store=store,
            node_resolver=lambda node_id, graph: _Step(),
            run_id=admitted.run_id,
            run_store=run_store,
        )

    orphaned = await run_store.list_node_runs(admitted.run_id)
    assert len(orphaned) == 1

    resumed = await traversal.resume_durable_graph(
        admitted.run_id,
        store=store,
        node_resolver=lambda node_id, graph: _Step(),
        run_store=run_store,
    )

    canonical = await run_store.list_node_runs(admitted.run_id)
    assert resumed.status is RunStatus.COMPLETED
    assert [item.node_run_id for item in canonical] == [orphaned[0].node_run_id]


async def test_retry_adopts_attempt_created_before_checkpoint_failure() -> None:
    """Retry mirrors the canonical Attempt instead of minting a second identity."""
    base_store, run_store, _execution_store, record, node_run_id = await _bound_execution_store()
    store = _FailNextUpdateStore()
    await store.create(record)
    store.fail_updates = 1
    execution_store = DurableRunExecutionStore(
        store,
        run_id=record.run_id,
        run_store=run_store,
    )

    with pytest.raises(RuntimeError, match="injected checkpoint failure"):
        await execution_store.create_attempt(node_run_id, executor_id="graph.node")

    orphaned = await run_store.list_attempts(node_run_id)
    assert len(orphaned) == 1

    adopted = await execution_store.create_attempt(node_run_id, executor_id="graph.node")

    assert adopted.attempt_id == orphaned[0].attempt_id
    assert [item.attempt_id for item in await run_store.list_attempts(node_run_id)] == [
        orphaned[0].attempt_id
    ]
    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert [item.attempt_id for item in persisted.attempts] == [orphaned[0].attempt_id]
    assert await base_store.get(record.run_id) is not None


async def test_scoped_reclaim_settles_canonical_attempt_before_immediate_retry() -> None:
    """One Run's recovery must not depend on a later global lease sweep."""
    store, run_store, execution_store, record, node_run_id = await _bound_execution_store()
    attempt = await execution_store.create_attempt(
        node_run_id,
        lease_holder="worker-1",
        lease_ttl=timedelta(seconds=1),
    )
    assert attempt.execution_lease is not None
    after_expiry = attempt.execution_lease.expires_at + timedelta(microseconds=1)

    reclaimed = await execution_store.reclaim_expired_attempts(now=after_expiry)

    assert [item.attempt_id for item in reclaimed] == [attempt.attempt_id]
    canonical = await run_store.get_attempt(attempt.attempt_id)
    assert canonical is not None
    assert canonical.status is reclaimed[0].status

    retry = await execution_store.create_attempt(node_run_id, executor_id="retry")
    assert retry.ordinal == attempt.ordinal + 1
    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert [item.attempt_id for item in persisted.attempts] == [
        attempt.attempt_id,
        retry.attempt_id,
    ]
