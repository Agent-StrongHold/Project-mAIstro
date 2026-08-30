"""Exhausted domain failure keeps physical evidence while Graph work may continue."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext, NodeResult
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import AttemptStatus, RunStatus


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "unused"


class _AlwaysFails(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.continue_on_failure"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    def __init__(self) -> None:
        self.calls = 0

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        del inputs, ctx
        self.calls += 1
        raise ValueError("domain failure")


async def test_exhausted_failure_completes_logically_without_rewriting_attempt() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-soft-failure")
    project = await projects.create(
        workspace_id="ws-soft-failure",
        parent_project_id=root.project_id,
        name="Soft failure",
    )
    run_store = InMemoryRunStore(project_store=projects)
    node = _AlwaysFails()
    graph = Graph(
        workspace_id="ws-soft-failure",
        project_id=project.project_id,
        name="soft failure",
        nodes=[
            Node(
                node_id="step",
                node_type=node.kind,
                policies={"max_attempts": 2, "continue_on_failure": True},
            )
        ],
    )
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)

    record = await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda node_id, _graph: node,
        run_id=admitted.run_id,
        run_store=run_store,
    )

    assert record.status is RunStatus.COMPLETED
    assert node.calls == 2
    node_runs = await run_store.list_node_runs(record.run_id)
    assert [item.status for item in node_runs] == [RunStatus.FAILED, RunStatus.COMPLETED]
    accepted = node_runs[-1].accepted_outcome
    assert accepted is not None
    physical = NodeResult.model_validate(accepted.attempt_result.result)
    assert physical.success is False
    assert physical.status == "failed"
    attempts = await run_store.list_attempts(node_runs[-1].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED
