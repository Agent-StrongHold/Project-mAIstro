"""Parity coverage for real durable Graph frontier execution."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus
from maistro.graph.durable_runs.executor import _next_nodes
from maistro.graph.nodes import BaseNode, NodeContext, get_node, register_node
from maistro.graph.nodes.base import NodeResult

from .._canonical_helpers import run_legacy_dag_fixture as run_durable_dag


class _EmptyIn(BaseModel):
    pass


class _StartOut(BaseModel):
    seed: str


class _LeftOut(BaseModel):
    left: str


class _RightOut(BaseModel):
    right: str


class _JoinIn(BaseModel):
    left: str
    right: str


class _JoinOut(BaseModel):
    combined: str


class _StartNode(BaseNode[_EmptyIn, _StartOut]):
    kind: ClassVar[str] = "test.frontier.start"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _StartOut

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _StartOut:
        return _StartOut(seed="go")


class _Barrier:
    started: ClassVar[int] = 0
    both_started: ClassVar[asyncio.Event | None] = None

    @classmethod
    def reset(cls) -> None:
        cls.started = 0
        cls.both_started = asyncio.Event()

    @classmethod
    async def arrive(cls) -> None:
        assert cls.both_started is not None
        cls.started += 1
        if cls.started == 2:
            cls.both_started.set()
        await asyncio.wait_for(cls.both_started.wait(), timeout=1.0)


class _LeftNode(BaseNode[_EmptyIn, _LeftOut]):
    kind: ClassVar[str] = "test.frontier.left"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _LeftOut

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _LeftOut:
        await _Barrier.arrive()
        await asyncio.sleep(0.01)
        return _LeftOut(left="L")


class _RightNode(BaseNode[_EmptyIn, _RightOut]):
    kind: ClassVar[str] = "test.frontier.right"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _RightOut

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _RightOut:
        await _Barrier.arrive()
        return _RightOut(right="R")


class _JoinNode(BaseNode[_JoinIn, _JoinOut]):
    kind: ClassVar[str] = "test.frontier.join"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _JoinIn
    output_schema: ClassVar[type[BaseModel]] = _JoinOut

    async def _execute(self, inputs: _JoinIn, ctx: NodeContext) -> _JoinOut:
        return _JoinOut(combined=inputs.left + inputs.right)


for _cls in (_StartNode, _LeftNode, _RightNode, _JoinNode):
    with contextlib.suppress(ValueError):
        register_node(_cls)


def _resolver(node_id: str, dag: dict[str, Any]) -> BaseNode[Any, Any]:
    for raw in dag["nodes"]:
        if raw["id"] == node_id:
            return get_node(raw["kind"])()
    raise KeyError(node_id)


def _fanout_dag() -> dict[str, Any]:
    return {
        "id": "frontier-fanout",
        "name": "fan-out then fan-in",
        "entry_node": "start",
        "nodes": [
            {"id": "start", "kind": _StartNode.kind},
            {"id": "left", "kind": _LeftNode.kind},
            {"id": "right", "kind": _RightNode.kind},
            {"id": "join", "kind": _JoinNode.kind},
        ],
        "edges": [
            {"id": "start-left", "from_node": "start", "to_node": "left"},
            {
                "id": "start-right",
                "from_node": "start",
                "to_node": "right",
                "parallel": True,
            },
            {"id": "left-join", "from_node": "left", "to_node": "join"},
            {"id": "right-join", "from_node": "right", "to_node": "join"},
        ],
    }


async def test_fanout_nodes_execute_concurrently_and_fanin_once() -> None:
    _Barrier.reset()
    store = InMemoryDurableRunStore()

    result = await asyncio.wait_for(
        run_durable_dag(_fanout_dag(), store=store, node_resolver=_resolver),
        timeout=2.0,
    )

    assert result.status is RunStatus.COMPLETED
    assert _Barrier.started == 2
    assert [run.node_id for run in result.node_runs] == ["start", "left", "right", "join"]
    assert result.node_runs[-1].result == {"combined": "LR"}
    assert result.graph_state.visit_counts == {"start": 1, "left": 1, "right": 1, "join": 1}


def test_parallel_routing_keeps_first_sequential_plus_all_parallel_edges() -> None:
    from .._canonical_helpers import graph_from_dag

    graph = graph_from_dag(_fanout_dag())
    targets, decisions = _next_nodes(
        graph,
        "start",
        "node-run-start",
        NodeResult(success=True, output={"seed": "go"}),
    )

    assert targets == ("left", "right")
    assert [decision.selected for decision in decisions] == [True, True]


async def test_fanin_is_correlated_to_both_source_node_runs() -> None:
    _Barrier.reset()
    store = InMemoryDurableRunStore()
    result = await run_durable_dag(_fanout_dag(), store=store, node_resolver=_resolver)

    by_node = {run.node_id: run for run in result.node_runs}
    selected_to_join = [
        decision
        for decision in result.graph_state.edge_decisions
        if decision.selected and decision.target_node_id == "join"
    ]

    assert [decision.source_node_id for decision in selected_to_join] == ["left", "right"]
    assert [decision.source_node_run_id for decision in selected_to_join] == [
        by_node["left"].node_run_id,
        by_node["right"].node_run_id,
    ]
    assert {decision.cycle for decision in selected_to_join} == {1}


async def test_frontier_order_is_deterministic_not_completion_order() -> None:
    _Barrier.reset()
    store = InMemoryDurableRunStore()
    result = await run_durable_dag(_fanout_dag(), store=store, node_resolver=_resolver)

    assert [(run.node_id, run.ordinal) for run in result.node_runs] == [
        ("start", 1),
        ("left", 2),
        ("right", 3),
        ("join", 4),
    ]
    assert result.graph_state.cycle == 3
