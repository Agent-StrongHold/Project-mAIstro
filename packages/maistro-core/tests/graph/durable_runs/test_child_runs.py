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


def test_a_child_runs_trace_is_its_own_and_links_back_through_the_parent() -> None:
    """#63's delegation leg: correlation survives a child Run.

    The child's events must name the child — not the parent Attempt they were
    launched from — while the durable `parent_run_id` stays the join between
    the two traces. Losing either half loses the question a delegation raises:
    what did the parent ask, and what did the child do about it.
    """

    async def scenario() -> None:
        from maistro.events.envelope import EventEnvelope, InMemoryEventStore

        store = InMemoryDurableRunStore()
        events = InMemoryEventStore()
        emitted: dict[str, str] = {}

        class _Emits(BaseNode[_EmptyIn, _NoopOut]):
            kind: ClassVar[str] = ""
            kind_category: ClassVar = "sync.transform"
            input_schema: ClassVar[type[BaseModel]] = _EmptyIn
            output_schema: ClassVar[type[BaseModel]] = _NoopOut
            launches_child: ClassVar[bool] = False

            async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _NoopOut:
                if self.launches_child:
                    child = await run_durable_graph(
                        _graph("child"),
                        store=store,
                        node_resolver=_child_resolver,
                        parent_run_id=ctx.run_id,
                        parent_node_run_id=ctx.node_run_id,
                    )
                    emitted["child_run_id"] = child.run.run_id
                stored = await events.append(
                    EventEnvelope(type="node.ran", workspace_id="w1")
                )
                emitted.setdefault(self.kind, stored.event_id)
                return _NoopOut(done=True)

        class _ParentNode(_Emits):
            kind: ClassVar[str] = "test.childrun.parent"
            launches_child: ClassVar[bool] = True

        class _ChildNode(_Emits):
            kind: ClassVar[str] = "test.childrun.child"

        def _child_resolver(node_id: str, graph: Any) -> BaseNode[_EmptyIn, _NoopOut]:
            return _ChildNode()

        def _parent_resolver(node_id: str, graph: Any) -> BaseNode[_EmptyIn, _NoopOut]:
            return _ParentNode()

        parent = await run_durable_graph(
            _graph("parent"), store=store, node_resolver=_parent_resolver
        )

        # The parent's event names the parent; the child's names the child.
        parent_event = await events.get(emitted["test.childrun.parent"])
        child_event = await events.get(emitted["test.childrun.child"])
        assert parent_event is not None and child_event is not None
        assert parent_event.run_id == parent.run.run_id
        assert parent_event.correlation_id == parent.run.run_id
        assert child_event.run_id == emitted["child_run_id"]
        assert child_event.run_id != parent.run.run_id
        assert child_event.correlation_id == emitted["child_run_id"]

        # Both live in the same Workspace stream, one sequence authority.
        assert parent_event.stream_id == child_event.stream_id == "workspace:w1"
        assert parent_event.sequence != child_event.sequence

        # The durable link between the two traces is the Run record itself.
        persisted = await store.get(emitted["child_run_id"])
        assert persisted is not None
        assert persisted.run.parent_run_id == parent.run.run_id
        assert persisted.run.parent_node_run_id == parent.node_runs[0].node_run_id

    asyncio.run(scenario())
