"""Test builders for the canonical Graph and durable Run contracts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import resume_durable_graph, run_durable_graph
from maistro.graph.durable_runs.protocol import DurableRunStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes.base import BaseNode
from maistro.runs.lifecycle import transition_run
from maistro.runs.model import GraphSnapshot, NodeRun, Run, RunStatus

LegacyResolver = Callable[[str, dict[str, Any]], BaseNode[Any, Any]]


def graph_from_dag(
    dag: dict[str, Any],
    *,
    workspace_id: str = "test-workspace",
    project_id: str = "test-project",
) -> Graph:
    """Translate legacy raw-DAG test fixtures at the test boundary only."""

    nodes: list[Node] = []
    for raw in dag.get("nodes", []):
        node_id = str(raw.get("id"))
        node_type = str(raw.get("kind") or raw.get("node_type") or "test.noop")
        metadata = {
            key: value
            for key, value in raw.items()
            if key not in {"id", "kind", "node_type", "inputs", "config", "parameters"}
        }
        nodes.append(
            Node(
                node_id=node_id,
                node_type=node_type,
                inputs=dict(raw.get("inputs") or {}),
                parameters=dict(raw.get("config") or raw.get("parameters") or {}),
                metadata=metadata,
            )
        )

    edges: list[Edge] = []
    for index, raw in enumerate(dag.get("edges", []), start=1):
        target = raw.get("to_node") or raw.get("to_role")
        if target is None:
            continue
        source = raw.get("from_node") or raw.get("from_role")
        metadata = {
            key: value
            for key, value in raw.items()
            if key
            not in {
                "id",
                "edge_id",
                "from_node",
                "from_role",
                "to_node",
                "to_role",
                "condition",
            }
        }
        edges.append(
            Edge(
                edge_id=str(raw.get("edge_id") or raw.get("id") or f"edge-{index}"),
                from_node=str(source),
                to_node=str(target),
                condition=str(raw["condition"]) if raw.get("condition") is not None else None,
                metadata=metadata,
            )
        )

    metadata = dict(dag.get("metadata") or {})
    if dag.get("entry_node") is not None:
        metadata["entry_node"] = str(dag["entry_node"])
    if dag.get("entry") is not None:
        metadata["entry"] = str(dag["entry"])

    return Graph(
        graph_id=str(dag.get("id") or dag.get("graph_id") or "test-graph"),
        workspace_id=workspace_id,
        project_id=project_id,
        name=str(dag.get("name") or dag.get("id") or "test-graph"),
        nodes=nodes,
        edges=edges,
        metadata=metadata,
    )


def _legacy_dag(graph: Graph) -> dict[str, Any]:
    """Project canonical Graphs back into the old resolver fixture shape."""

    return {
        "id": graph.graph_id,
        "name": graph.name,
        "entry_node": graph.metadata.get("entry_node"),
        "nodes": [
            {
                "id": node.node_id,
                "kind": node.node_type,
                "inputs": dict(node.inputs),
                "config": dict(node.parameters),
                **dict(node.metadata),
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "edge_id": edge.edge_id,
                "from_node": edge.from_node,
                "to_node": edge.to_node,
                "condition": edge.condition,
                **dict(edge.metadata),
            }
            for edge in graph.edges
        ],
    }


async def run_legacy_dag_fixture(
    dag: dict[str, Any],
    *,
    store: DurableRunStore,
    node_resolver: LegacyResolver,
    inputs: dict[str, Any] | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    run_id: str | None = None,
) -> DurableRunRecord:
    """Execute a raw legacy test fixture through the canonical public executor."""

    graph = graph_from_dag(dag, project_id=project_id or "test-project")

    def resolver(node_id: str, _graph: Graph) -> BaseNode[Any, Any]:
        return node_resolver(node_id, dag)

    return await run_durable_graph(
        graph,
        store=store,
        node_resolver=resolver,
        inputs=inputs,
        actor_principal_id=user_id,
        run_id=run_id,
    )


async def resume_legacy_dag_fixture(
    run_id: str,
    *,
    store: DurableRunStore,
    node_resolver: LegacyResolver,
) -> DurableRunRecord:
    """Resume canonical persistence while preserving old resolver test fixtures."""

    def resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
        return node_resolver(node_id, _legacy_dag(graph))

    return await resume_durable_graph(run_id, store=store, node_resolver=resolver)


def run_at_status(
    graph: Graph,
    *,
    run_id: str,
    status: RunStatus = RunStatus.RUNNING,
    actor_principal_id: str | None = None,
) -> Run:
    """Build a canonical Run in a requested reachable lifecycle state."""

    run = Run(
        run_id=run_id,
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        actor_principal_id=actor_principal_id,
    )
    if status is RunStatus.CREATED:
        return run
    if status is RunStatus.CANCELLED:
        return transition_run(run, RunStatus.CANCELLED)
    run = transition_run(run, RunStatus.QUEUED)
    if status is RunStatus.QUEUED:
        return run
    if status is RunStatus.TIMED_OUT:
        return transition_run(run, RunStatus.TIMED_OUT)
    run = transition_run(run, RunStatus.RUNNING)
    if status is RunStatus.RUNNING:
        return run
    return transition_run(run, status)


def durable_record(
    dag: dict[str, Any],
    *,
    run_id: str,
    status: RunStatus = RunStatus.RUNNING,
    active_node_id: str | None = None,
    node_runs: tuple[NodeRun, ...] = (),
    project_id: str = "test-project",
    workspace_id: str = "test-workspace",
    metadata: dict[str, Any] | None = None,
    blackboard_snapshot: dict[str, Any] | None = None,
    resume_at: datetime | None = None,
    version: int = 1,
) -> DurableRunRecord:
    """Build a canonical durable envelope for focused store/executor tests."""

    graph = graph_from_dag(dag, workspace_id=workspace_id, project_id=project_id)
    run = run_at_status(graph, run_id=run_id, status=status)
    state = GraphExecutionState(
        run_id=run_id,
        active_node_ids=(active_node_id,) if active_node_id is not None else (),
        blackboard_snapshot=blackboard_snapshot or {},
        metadata=metadata or {"initial_inputs": {}, "hitl_answers": {}},
    )
    return DurableRunRecord(
        run=run,
        graph_state=state,
        node_runs=node_runs,
        resume_at=resume_at,
        version=version,
    )


def now_utc() -> datetime:
    return datetime.now(UTC)
