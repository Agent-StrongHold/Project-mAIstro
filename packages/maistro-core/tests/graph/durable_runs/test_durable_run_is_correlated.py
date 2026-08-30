"""The durable graph binds its own Run before executing Attempts (#707).

This path never goes through `RunExecutionService`, which is where the Run is
otherwise bound: `run_durable_graph` constructs `AttemptExecutionService`
directly. So it had to bind the Run itself, and until it did, a top-level
durable execution named no Run — while a *child* durable graph launched from
inside a parent Attempt was worse, inheriting the parent's ambient `run_id` and
attributing its own nodes to the parent (Codex, #707).
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus, run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.observability.correlation import (
    ExecutionContext,
    bind_execution_context,
    current_execution_context,
)

pytestmark = [pytest.mark.contract("behavioral")]


class _Empty(BaseModel):
    pass


class _Done(BaseModel):
    text: str


class _Watching(BaseNode[_Empty, _Done]):
    """Records the ambient context from inside the node's own execution."""

    kind: ClassVar[str] = "test.correlation.watching"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Done
    seen: ClassVar[list[ExecutionContext]] = []

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Done:
        type(self).seen.append(current_execution_context())
        return _Done(text="done")


def _resolver(node_id: str, graph: Graph) -> Any:
    del graph
    assert node_id == "watch"
    return _Watching()


def _graph() -> Graph:
    return Graph(
        workspace_id="ws-1",
        project_id="proj-1",
        name="One watching node",
        nodes=[Node(node_id="watch", node_type=_Watching.kind)],
    )


@pytest.fixture(autouse=True)
def _clear_seen() -> Any:
    _Watching.seen = []
    yield
    _Watching.seen = []


class TestADurableRunNamesItself:
    async def test_a_node_runs_under_the_durable_runs_own_id(self) -> None:
        record = await run_durable_graph(
            _graph(), store=InMemoryDurableRunStore(), node_resolver=_resolver
        )

        assert record.status is RunStatus.COMPLETED
        [seen] = _Watching.seen
        assert seen.run_id == record.run_id
        assert seen.node_run_id
        assert seen.attempt_id

    async def test_a_nested_durable_run_names_itself_and_not_its_caller(self) -> None:
        """The case that was actively wrong rather than merely missing: binding
        is additive, so with nothing overriding it a nested durable graph's
        nodes reported the surrounding Run as their own."""
        with bind_execution_context(run_id="outer-run", attempt_id="outer-attempt"):
            record = await run_durable_graph(
                _graph(), store=InMemoryDurableRunStore(), node_resolver=_resolver
            )

        [seen] = _Watching.seen
        assert seen.run_id == record.run_id
        assert seen.run_id != "outer-run"
        assert seen.attempt_id != "outer-attempt"

    async def test_the_binding_does_not_outlive_the_run(self) -> None:
        with bind_execution_context(run_id="outer-run"):
            await run_durable_graph(
                _graph(), store=InMemoryDurableRunStore(), node_resolver=_resolver
            )
            assert current_execution_context().run_id == "outer-run"
        assert current_execution_context().run_id == ""
