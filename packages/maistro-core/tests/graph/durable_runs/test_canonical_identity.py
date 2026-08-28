"""Graph execution obtains its Run identity from the canonical store (#44).

The first of the three construction sites ADR-082826-d9f5 converges. Before
this, `_new_run` minted a `Run` in memory and the whole `DurableRunRecord` was
handed to a store that had never seen it — which is why `GET /v1/runs/{id}`
could not find a graph Run, and why an adapter could not have fixed it: every
id existed before the canonical store was involved, so persisting the record
would have meant the store accepting identities its caller assigned first.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus


class _StepIn(BaseModel):
    pass


class _StepOut(BaseModel):
    text: str = "done"


class _Step(BaseNode[_StepIn, _StepOut]):
    kind: ClassVar[str] = "test.canonical_identity.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        return _StepOut()


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-canonical")
    project = await projects.create(
        workspace_id="ws-canonical", parent_project_id=root.project_id, name="Graphs"
    )
    return InMemoryRunStore(project_store=projects), "ws-canonical", project.project_id


def _graph(workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="one step",
        nodes=[Node(node_id="step", node_type=_Step.kind)],
    )


def _resolver(node_id: str, graph: Any) -> Any:
    return _Step()


async def test_a_graph_run_is_findable_in_the_canonical_store() -> None:
    """The symptom #44 exists to remove: graph Runs invisible to the spine."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_store=run_store,
    )

    canonical = await run_store.get_run(record.run.run_id)
    assert canonical is not None, "the Run the graph executed is in the canonical store"
    assert canonical.workspace_id == workspace_id
    assert canonical.project_id == project_id
    assert canonical.provenance["executor"] == "durable_graph"


async def test_the_identity_is_the_stores_not_the_records() -> None:
    """The record's `run` is a projection of a row that already exists, rather
    than an id minted here and persisted afterwards."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_store=run_store,
    )

    listed = await run_store.list_by_status(RunStatus.RUNNING, limit=100)
    listed += await run_store.list_by_status(RunStatus.COMPLETED, limit=100)
    assert record.run.run_id in {run.run_id for run in listed}


async def test_without_a_canonical_store_the_previous_behaviour_is_unchanged() -> None:
    """`run_store` is opt-in: a caller with no spine wired still runs, exactly
    as it did before, rather than failing to start."""
    workspace_id, project_id = "ws-none", "project-none"

    record = await run_durable_graph(
        Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name="one step",
            nodes=[Node(node_id="step", node_type=_Step.kind)],
        ),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
    )

    assert record.run.run_id
    assert record.status is RunStatus.COMPLETED


async def test_a_pinned_run_id_still_wins_over_canonical_creation() -> None:
    """An already-admitted Run being executed must not get a second identity —
    creating one is the duplicate this convergence removes."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_id="pinned-run-1",
        run_store=run_store,
    )

    assert record.run.run_id == "pinned-run-1"
    assert await run_store.get_run("pinned-run-1") is None
