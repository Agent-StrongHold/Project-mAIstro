"""Child-Run linkage through the canonical durable launch path."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus, run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext


class _EmptyIn(BaseModel):
    pass


class _NoopOut(BaseModel):
    done: bool


class _NoopNode(BaseNode[_EmptyIn, _NoopOut]):
    kind: ClassVar[str] = "test.childrun.noop"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _NoopOut

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _NoopOut:
        return _NoopOut(done=True)


def _graph(name: str) -> Graph:
    return Graph(
        workspace_id="w1",
        project_id="p1",
        name=name,
        nodes=[Node(node_id="only", node_type="test.childrun.noop")],
        metadata={"entry_node": "only"},
    )


def _resolver(node_id: str, graph: Any) -> _NoopNode:
    return _NoopNode()


def test_launch_without_parentage_stays_root() -> None:
    record = asyncio.run(
        run_durable_graph(_graph("root"), store=InMemoryDurableRunStore(), node_resolver=_resolver)
    )
    assert record.run.status is RunStatus.COMPLETED
    assert record.run.parent_run_id is None
    assert record.run.parent_node_run_id is None


def test_child_run_carries_and_persists_parent_identity() -> None:
    async def scenario() -> None:
        store = InMemoryDurableRunStore()
        parent = await run_durable_graph(_graph("parent"), store=store, node_resolver=_resolver)
        parent_node_run = parent.node_runs[0]

        child = await run_durable_graph(
            _graph("child"),
            store=store,
            node_resolver=_resolver,
            parent_run_id=parent.run.run_id,
            parent_node_run_id=parent_node_run.node_run_id,
        )
        assert child.run.parent_run_id == parent.run.run_id
        assert child.run.parent_node_run_id == parent_node_run.node_run_id

        # Parentage is Run state, not launch-call state: it survives the store.
        persisted = await store.get(child.run.run_id)
        assert persisted is not None
        assert persisted.run.parent_run_id == parent.run.run_id
        assert persisted.run.parent_node_run_id == parent_node_run.node_run_id

    asyncio.run(scenario())


def test_run_refuses_to_be_its_own_parent() -> None:
    with pytest.raises(ValueError, match="own parent"):
        asyncio.run(
            run_durable_graph(
                _graph("selfie"),
                store=InMemoryDurableRunStore(),
                node_resolver=_resolver,
                run_id="run-fixed",
                parent_run_id="run-fixed",
            )
        )
