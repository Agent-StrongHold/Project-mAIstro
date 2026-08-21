"""Regression coverage for durable frontier reconciliation edge cases."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus
from maistro.graph.nodes.base import BaseNode, NodeContext, pause_until

from .._canonical_helpers import run_legacy_dag_fixture


class _Empty(BaseModel):
    pass


class _LeftOut(BaseModel):
    left: str


class _RightOut(BaseModel):
    right: str


class _JoinIn(BaseModel):
    left: str
    right: str


class _JoinOut(BaseModel):
    combined: str


class _TextIn(BaseModel):
    text: str = "default"


class _TextOut(BaseModel):
    text: str


class _EmptyNode(BaseNode[_Empty, _Empty]):
    kind: ClassVar[str] = "test.frontier-reconcile.empty"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Empty

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Empty:
        return _Empty()


class _LeftNode(BaseNode[_Empty, _LeftOut]):
    kind: ClassVar[str] = "test.frontier-reconcile.left"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _LeftOut

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _LeftOut:
        return _LeftOut(left="L")


class _RightNode(BaseNode[_Empty, _RightOut]):
    kind: ClassVar[str] = "test.frontier-reconcile.right"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _RightOut

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _RightOut:
        return _RightOut(right="R")


class _MidNode(BaseNode[_RightOut, _RightOut]):
    kind: ClassVar[str] = "test.frontier-reconcile.mid"
    input_schema: ClassVar[type[BaseModel]] = _RightOut
    output_schema: ClassVar[type[BaseModel]] = _RightOut

    async def _execute(self, inputs: _RightOut, ctx: NodeContext) -> _RightOut:
        return inputs


class _JoinNode(BaseNode[_JoinIn, _JoinOut]):
    kind: ClassVar[str] = "test.frontier-reconcile.join"
    input_schema: ClassVar[type[BaseModel]] = _JoinIn
    output_schema: ClassVar[type[BaseModel]] = _JoinOut

    async def _execute(self, inputs: _JoinIn, ctx: NodeContext) -> _JoinOut:
        return _JoinOut(combined=inputs.left + inputs.right)


class _TextNode(BaseNode[_TextIn, _TextOut]):
    kind: ClassVar[str] = "test.frontier-reconcile.text"
    input_schema: ClassVar[type[BaseModel]] = _TextIn
    output_schema: ClassVar[type[BaseModel]] = _TextOut

    async def _execute(self, inputs: _TextIn, ctx: NodeContext) -> _TextOut:
        return _TextOut(text=inputs.text)


class _FailNode(BaseNode[_Empty, _Empty]):
    kind: ClassVar[str] = "test.frontier-reconcile.fail"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Empty

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Empty:
        raise RuntimeError("boom")


class _PauseNode(BaseNode[_Empty, _Empty]):
    kind: ClassVar[str] = "test.frontier-reconcile.pause"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Empty

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Empty:
        pause_until("awaiting_human_answer", metadata={"question": "Continue?"})
        raise AssertionError("pause_until must not return")


_NODE_BY_ID: dict[str, type[BaseNode[Any, Any]]] = {
    "start": _EmptyNode,
    "left": _LeftNode,
    "right": _RightNode,
    "mid": _MidNode,
    "join": _JoinNode,
    "producer": _EmptyNode,
    "consumer": _TextNode,
    "fail": _FailNode,
    "pause": _PauseNode,
}


def _resolver(node_id: str, dag: dict[str, Any]) -> BaseNode[Any, Any]:
    return _NODE_BY_ID[node_id]()


async def test_unequal_parallel_branches_wait_for_fanin_and_merge_cross_cycle_outputs() -> None:
    dag = {
        "id": "unequal-fanin",
        "entry_node": "start",
        "nodes": [
            {"id": "start", "kind": _EmptyNode.kind},
            {"id": "left", "kind": _LeftNode.kind},
            {"id": "right", "kind": _RightNode.kind},
            {"id": "mid", "kind": _MidNode.kind},
            {"id": "join", "kind": _JoinNode.kind},
        ],
        "edges": [
            {"from_node": "start", "to_node": "left"},
            {"from_node": "start", "to_node": "right", "parallel": True},
            {"from_node": "left", "to_node": "join"},
            {"from_node": "right", "to_node": "mid"},
            {"from_node": "mid", "to_node": "join"},
        ],
    }

    result = await run_legacy_dag_fixture(
        dag,
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
    )

    assert result.status is RunStatus.COMPLETED
    assert [node.node_id for node in result.node_runs] == [
        "start",
        "left",
        "right",
        "mid",
        "join",
    ]
    assert result.node_runs[-1].result == {"combined": "LR"}
    assert result.graph_state.visit_counts["join"] == 1


async def test_empty_predecessor_output_does_not_restore_initial_inputs() -> None:
    dag = {
        "id": "empty-predecessor-output",
        "entry_node": "producer",
        "nodes": [
            {"id": "producer", "kind": _EmptyNode.kind},
            {"id": "consumer", "kind": _TextNode.kind},
        ],
        "edges": [{"from_node": "producer", "to_node": "consumer"}],
    }

    result = await run_legacy_dag_fixture(
        dag,
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        inputs={"text": "stale"},
    )

    assert result.status is RunStatus.COMPLETED
    assert result.node_runs[-1].result == {"text": "default"}


async def test_failed_frontier_cancels_paused_sibling() -> None:
    dag = {
        "id": "fail-with-paused-sibling",
        "entry_node": "start",
        "nodes": [
            {"id": "start", "kind": _EmptyNode.kind},
            {"id": "fail", "kind": _FailNode.kind},
            {"id": "pause", "kind": _PauseNode.kind},
        ],
        "edges": [
            {"from_node": "start", "to_node": "fail"},
            {"from_node": "start", "to_node": "pause", "parallel": True},
        ],
    }

    result = await run_legacy_dag_fixture(
        dag,
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
    )

    by_node = {node.node_id: node for node in result.node_runs}
    assert result.status is RunStatus.FAILED
    assert by_node["fail"].status is RunStatus.FAILED
    assert by_node["pause"].status is RunStatus.CANCELLED
    assert all(
        node.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
        for node in result.node_runs
    )
