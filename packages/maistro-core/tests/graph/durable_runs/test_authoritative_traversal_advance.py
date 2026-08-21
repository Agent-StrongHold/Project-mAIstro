from __future__ import annotations

from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Edge, Graph, GraphExecutionState, Node, accepted_outcome_id
from maistro.graph.durable_runs import (
    DurableRunRecord,
    InMemoryDurableRunStore,
    RunStatus,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.nodes import BaseNode, NodeContext, NodeResult
from maistro.runs import Attempt, AttemptStatus, GraphSnapshot, NodeRun, Run


class _Empty(BaseModel):
    pass


class _Value(BaseModel):
    value: str


class _First(BaseNode[_Empty, _Value]):
    kind: ClassVar[str] = "test.authoritative.first"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Value

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Value:
        del inputs, ctx
        return _Value(value="first")


class _Second(BaseNode[_Empty, _Value]):
    kind: ClassVar[str] = "test.authoritative.second"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Value

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Value:
        del inputs, ctx
        return _Value(value="second")


class _DomainFailure(BaseNode[_Empty, _Value]):
    kind: ClassVar[str] = "test.authoritative.failure"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Value

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Value:
        del inputs, ctx
        raise RuntimeError("domain rejected result")


class _Recovery(BaseNode[_Empty, _Value]):
    kind: ClassVar[str] = "test.authoritative.recovery"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Value
    calls: ClassVar[int] = 0

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Value:
        del inputs, ctx
        type(self).calls += 1
        return _Value(value="redispatched")


def _two_node_graph() -> Graph:
    return Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Authoritative traversal",
        nodes=[
            Node(node_id="first", node_type=_First.kind),
            Node(node_id="second", node_type=_Second.kind),
        ],
        edges=[Edge(edge_id="first-second", from_node="first", to_node="second")],
        metadata={"entry_node": "first"},
    )


def _resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    del graph
    return {"first": _First, "second": _Second}[node_id]()


def _failure_graph() -> Graph:
    return Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Logical failure",
        nodes=[Node(node_id="failure", node_type=_DomainFailure.kind)],
        metadata={"entry_node": "failure"},
    )


def _failure_resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    del graph
    assert node_id == "failure"
    return _DomainFailure()


def _recovery_record() -> DurableRunRecord:
    graph = Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Recovered completion",
        nodes=[Node(node_id="recover", node_type=_Recovery.kind)],
        metadata={"entry_node": "recover"},
    )
    run = Run(
        run_id="recovery-run",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.RUNNING,
    )
    node_run = NodeRun(
        node_run_id="recovery-node-run",
        run_id=run.run_id,
        node_id="recover",
        ordinal=1,
        status=RunStatus.RUNNING,
    )
    result = NodeResult(success=True, output={"value": "already-durable"})
    attempt = Attempt(
        attempt_id="recovery-attempt",
        node_run_id=node_run.node_run_id,
        ordinal=1,
        status=AttemptStatus.COMPLETED,
        started_at=run.created_at,
        finished_at=run.created_at,
        result=result,
    )
    return DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("recover",)),
        node_runs=(node_run,),
        attempts=(attempt,),
        version=1,
    )


def _recovery_resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    del graph
    assert node_id == "recover"
    return _Recovery()


@pytest.mark.asyncio
async def test_each_advancing_frontier_persists_accepted_outcome_and_commit() -> None:
    store = InMemoryDurableRunStore()

    record = await run_durable_graph(
        _two_node_graph(),
        store=store,
        node_resolver=_resolver,
    )

    assert record.status is RunStatus.COMPLETED
    assert len(record.traversal_commits) == 2
    assert [commit.commit_sequence for commit in record.traversal_commits] == [1, 2]
    assert (
        record.traversal_commits[1].prior_commit_id
        == record.traversal_commits[0].traversal_commit_id
    )
    assert len(record.traversal_checkpoints) == 1
    checkpoint = record.traversal_checkpoints[0]
    assert record.traversal_commits[1].checkpoint_id == checkpoint.traversal_checkpoint_id
    assert record.traversal_commits[1].prior_state_hash == checkpoint.state_hash
    assert (
        record.traversal_commits[1].prior_state_hash
        != record.traversal_commits[0].resulting_state_hash
    )
    assert all(node_run.accepted_outcome is not None for node_run in record.node_runs)
    for commit, node_run in zip(record.traversal_commits, record.node_runs, strict=True):
        assert node_run.accepted_outcome is not None
        assert commit.ordered_source_node_run_ids == (node_run.node_run_id,)
        assert commit.accepted_outcome_ids == (accepted_outcome_id(node_run.accepted_outcome),)


@pytest.mark.asyncio
async def test_physical_completion_can_be_accepted_as_logical_failure_without_advancement() -> None:
    store = InMemoryDurableRunStore()

    record = await run_durable_graph(
        _failure_graph(),
        store=store,
        node_resolver=_failure_resolver,
    )

    assert record.status is RunStatus.FAILED
    assert len(record.attempts) == 1
    assert record.attempts[0].status is AttemptStatus.COMPLETED
    assert len(record.node_runs) == 1
    node_run = record.node_runs[0]
    assert node_run.status is RunStatus.FAILED
    assert node_run.accepted_outcome is not None
    assert node_run.accepted_outcome.logical_status is RunStatus.FAILED
    assert "domain rejected result" in (node_run.error or "")
    assert record.traversal_commits == ()


@pytest.mark.asyncio
async def test_recovery_folds_persisted_completion_without_redispatch_and_commits_once() -> None:
    _Recovery.calls = 0
    store = InMemoryDurableRunStore()
    await store.create(_recovery_record())

    record = await resume_durable_graph(
        "recovery-run",
        store=store,
        node_resolver=_recovery_resolver,
    )

    assert _Recovery.calls == 0
    assert len(record.attempts) == 1
    assert record.node_runs[0].status is RunStatus.COMPLETED
    assert record.node_runs[0].accepted_outcome is not None
    assert record.node_runs[0].result == {"value": "already-durable"}
    assert len(record.traversal_commits) == 1
    assert record.traversal_commits[0].ordered_source_node_run_ids == (
        record.node_runs[0].node_run_id,
    )
