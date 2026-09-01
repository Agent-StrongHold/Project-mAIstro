"""Canonical execution adapter for Hive's legacy stored DAG shape.

The stored/UI DAG schema predates canonical ``Graph`` definitions. This module
translates that definition and then hands all traversal, concurrency,
NodeRun/Attempt creation, failure folding, and terminal-state authority to
``run_durable_graph``. The only legacy behavior retained is one-node execution
via :class:`services.legacy_dag_node.LegacyConductorNode`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from typing import Any

from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import RunStatus, run_durable_graph
from maistro.runs.model import TERMINAL_RUN_STATUSES
from services.dag_agents import _container, get_run_store
from services.legacy_dag_node import LegacyConductorNode, OnResponseHook
from services.node_metrics_store import record_run_completion

logger = logging.getLogger(__name__)
_COMPAT_SCOPE = "hive-standalone-compat"


def _raw_nodes(dag_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = dag_data.get("nodes", [])
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("DAG has no nodes; refusing success-with-zero-work")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in nodes:
        if not isinstance(raw, Mapping):
            raise ValueError("DAG node must be an object")
        node = dict(raw)
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            raise ValueError("DAG node is missing id")
        if node_id in seen:
            raise ValueError(f"duplicate DAG node id: {node_id!r}")
        seen.add(node_id)
        normalized.append(node)
    return normalized


def _raw_edges(dag_data: Mapping[str, Any], node_ids: set[str]) -> list[dict[str, Any]]:
    edges = dag_data.get("edges", [])
    if not isinstance(edges, list):
        raise ValueError("DAG edges must be a list")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(edges):
        if not isinstance(raw, Mapping):
            raise ValueError("DAG edge must be an object")
        edge = dict(raw)
        src = str(edge.get("from_node") or "").strip()
        dst_value = edge.get("to_node")
        # Historical evolution genomes use to_node=None as a terminal marker.
        if dst_value in (None, ""):
            continue
        dst = str(dst_value).strip()
        if src not in node_ids or dst not in node_ids:
            raise ValueError(
                f"edge {edge.get('id', index)!r} references node outside DAG: {src!r}->{dst!r}"
            )
        normalized.append(edge)
    return normalized


def _entry_node(dag_data: Mapping[str, Any], nodes: list[dict[str, Any]]) -> str:
    explicit = str(dag_data.get("entry_node") or "").strip()
    ids = {str(node["id"]) for node in nodes}
    if explicit:
        if explicit not in ids:
            raise ValueError(f"DAG entry node {explicit!r} does not exist")
        return explicit
    incoming = {
        str(edge.get("to_node"))
        for edge in dag_data.get("edges", [])
        if isinstance(edge, Mapping) and edge.get("to_node")
    }
    roots = [str(node["id"]) for node in nodes if str(node["id"]) not in incoming]
    if len(roots) == 1:
        return roots[0]
    if not roots:
        # The cycle validator below will produce the more useful message.
        return str(nodes[0]["id"])
    raise ValueError(
        "DAG has multiple disconnected entry roots; choose one entry_node or connect the graph: "
        + ", ".join(roots)
    )


def _validate_acyclic_and_reachable(
    entry: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    adjacency: dict[str, list[str]] = {str(node["id"]): [] for node in nodes}
    indegree: dict[str, int] = {node_id: 0 for node_id in adjacency}
    for edge in edges:
        src, dst = str(edge["from_node"]), str(edge["to_node"])
        adjacency[src].append(dst)
        indegree[dst] += 1

    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(nodes):
        raise ValueError("cyclic DAG rejected before execution")

    reachable = {entry}
    frontier = [entry]
    while frontier:
        current = frontier.pop()
        for target in adjacency[current]:
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    missing = sorted(set(adjacency) - reachable)
    if missing:
        raise ValueError(
            "DAG contains nodes unreachable from its entry node: " + ", ".join(missing)
        )


def graph_from_legacy_dag(
    dag_data: Mapping[str, Any], *, workspace_id: str, project_id: str
) -> Graph:
    """Translate one legacy stored DAG into an immutable canonical Graph definition."""
    nodes = _raw_nodes(dag_data)
    node_ids = {str(node["id"]) for node in nodes}
    raw_edges = _raw_edges(dag_data, node_ids)
    entry = _entry_node(dag_data, nodes)
    _validate_acyclic_and_reachable(entry, nodes, raw_edges)

    graph_nodes = [
        Node(
            node_id=str(raw["id"]),
            node_type="hive.legacy_node",
            name=str(raw.get("name") or raw["id"]),
            metadata={
                "role": str(raw.get("role") or "worker"),
                "legacy_node": dict(raw),
            },
        )
        for raw in nodes
    ]
    graph_edges = [
        Edge(
            edge_id=str(raw.get("id") or f"{raw['from_node']}->{raw['to_node']}"),
            from_node=str(raw["from_node"]),
            to_node=str(raw["to_node"]),
            condition=raw.get("condition"),
            # Legacy DAG edges were dependency edges, so every eligible
            # outgoing edge participates in fan-out. Canonical Graph defaults
            # to first sequential edge unless this is explicit.
            metadata={"parallel": True, "legacy_dependency_edge": True},
        )
        for raw in raw_edges
    ]
    graph_kwargs: dict[str, Any] = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "name": str(dag_data.get("name") or "Unnamed DAG"),
        "description": str(dag_data.get("description") or ""),
        "nodes": graph_nodes,
        "edges": graph_edges,
        "metadata": {
            "entry_node": entry,
            "source": "hive_legacy_dag",
            "legacy_dag_id": str(dag_data.get("id") or ""),
        },
    }
    legacy_id = str(dag_data.get("id") or "").strip()
    if legacy_id:
        graph_kwargs["graph_id"] = legacy_id
    return Graph(**graph_kwargs)


async def _scope(
    dag_data: Mapping[str, Any],
    *,
    workspace_id: str | None,
    project_id: str | None,
) -> tuple[str, str, Any, Any]:
    container = _container()
    if container is None:
        return (
            workspace_id or str(dag_data.get("workspace_id") or _COMPAT_SCOPE),
            project_id or str(dag_data.get("project_id") or _COMPAT_SCOPE),
            None,
            None,
        )

    resolved_workspace = (
        workspace_id
        or str(dag_data.get("workspace_id") or "").strip()
        or str(container.config.workspace_id)
    )
    resolved_project = project_id or str(dag_data.get("project_id") or "").strip() or None
    if resolved_project is None:
        root = await container.project_scope_store.root_for_workspace(resolved_workspace)
        resolved_project = root.project_id
    return resolved_workspace, resolved_project, container.run_store, container


def _node_env(
    dag_data: Mapping[str, Any], *, user_id: str, user_credentials: Mapping[str, str] | None
) -> dict[str, str]:
    environment = {
        "LITELLM_API_BASE": os.environ.get("LITELLM_API_BASE", ""),
        "LITELLM_API_KEY": os.environ.get("LITELLM_API_KEY", ""),
        "CHAT_DEFAULT_MODEL": os.environ.get("CHAT_DEFAULT_MODEL", "gemini-3.5-flash"),
        "DAG_USER_ID": user_id,
        "DAG_ID": str(dag_data.get("id") or ""),
        "PATH": os.environ.get("PATH", ""),
    }
    for key, value in (user_credentials or {}).items():
        environment[f"USER_CRED_{key.upper()}"] = value
    return environment


def _resolver(
    raw_by_id: Mapping[str, dict[str, Any]],
    *,
    task_desc: str,
    node_env: dict[str, str],
    execution_mode: str,
    on_response: OnResponseHook | None,
    llm_builder: Callable[[OnResponseHook | None], Any] | None,
):
    def resolve(node_id: str, _graph: Graph) -> LegacyConductorNode:
        try:
            raw = raw_by_id[node_id]
        except KeyError as exc:
            raise KeyError(f"legacy DAG node {node_id!r} is missing from adapter map") from exc
        return LegacyConductorNode(
            raw_node=raw,
            task_desc=task_desc,
            node_env=node_env,
            execution_mode=execution_mode,
            on_response=on_response,
            llm_builder=llm_builder,
        )

    return resolve


def _node_results(
    record: Any, raw_by_id: Mapping[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    projected: dict[str, dict[str, Any]] = {}
    for node_run in record.node_runs:
        raw = raw_by_id.get(node_run.node_id, {})
        result = node_run.result if isinstance(node_run.result, Mapping) else {}
        projected[node_run.node_id] = {
            "role": str(result.get("role") or raw.get("role") or "worker"),
            "response": str(result.get("response") or node_run.error or ""),
            "success": node_run.status is RunStatus.COMPLETED,
            "model": result.get("model") or raw.get("model"),
            **({"isolation": result.get("isolation")} if result.get("isolation") else {}),
        }
    return projected


def _project(record: Any, raw_by_id: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    status = record.run.status
    blackboard = record.graph_state.blackboard_snapshot
    node_results = _node_results(record, raw_by_id)
    error = record.run.error
    if not error:
        error = next(
            (value["response"] for value in node_results.values() if not value["success"]),
            None,
        )
    return {
        "status": status.value,
        "run_id": record.run_id,
        "cycles": record.graph_state.cycle,
        "node_results": node_results,
        "annotations": dict(blackboard.get("node_annotations") or {}),
        **({"error": str(error)} if error else {}),
    }


async def execute_dag(
    dag_data: dict,
    *,
    user_id: str = "",
    user_credentials: dict[str, str] | None = None,
    execution_mode: str = "autonomous",
    on_response: OnResponseHook | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    llm_builder: Callable[[OnResponseHook | None], Any] | None = None,
) -> dict[str, Any]:
    """Run a legacy Hive DAG as one canonical durable Graph Run."""
    resolved_workspace, resolved_project, canonical_run_store, _ = await _scope(
        dag_data,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    graph = graph_from_legacy_dag(
        dag_data,
        workspace_id=resolved_workspace,
        project_id=resolved_project,
    )
    raw_nodes = _raw_nodes(dag_data)
    raw_by_id = {str(raw["id"]): raw for raw in raw_nodes}
    task_desc = str(dag_data.get("description") or dag_data.get("name") or "")
    admitted_run_id = None
    provenance = {
        "admission_source": "hive_legacy_dag",
        "legacy_dag_id": str(dag_data.get("id") or ""),
        "executor": "durable_graph",
    }
    if canonical_run_store is not None:
        admitted = await canonical_run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=user_id or None,
            provenance=provenance,
        )
        admitted_run_id = admitted.run_id

    record = await run_durable_graph(
        graph,
        store=get_run_store(),
        node_resolver=_resolver(
            raw_by_id,
            task_desc=task_desc,
            node_env=_node_env(
                dag_data,
                user_id=user_id,
                user_credentials=user_credentials,
            ),
            execution_mode=execution_mode,
            on_response=on_response,
            llm_builder=llm_builder,
        ),
        actor_principal_id=user_id or None,
        run_id=admitted_run_id,
        run_store=canonical_run_store,
        provenance=provenance,
    )
    if record.run.status in TERMINAL_RUN_STATUSES:
        try:
            record_run_completion(record)
        except Exception:
            logger.warning(
                "node_metrics_not_recorded run_id=%s dag_id=%s",
                record.run_id,
                dag_data.get("id", ""),
                exc_info=True,
            )
    return _project(record, raw_by_id)


def genome_to_dag(genome: Any) -> dict[str, Any]:
    nodes = [
        {
            "id": node.id,
            "name": f"{node.role}-{node.id[:6]}",
            "role": node.role,
            "model": node.model,
            "prompt": node.system_prompt,
            "strategy": node.strategy,
            "temperature": node.temperature,
            "max_tokens": node.max_tokens,
            "max_tool_rounds": node.max_tool_rounds,
        }
        for node in genome.topology.nodes
    ]
    edges = [
        {
            "id": edge.id,
            "from_node": edge.from_node,
            "to_node": edge.to_node,
            "condition": edge.condition,
        }
        for edge in genome.topology.edges
    ]
    return {
        "name": genome.name,
        "description": (
            f"Evolved pipeline (gen={genome.generation}, fitness={genome.fitness_score})"
        ),
        "nodes": nodes,
        "edges": edges,
        "entry_node": genome.topology.entry_node,
        "max_cycles": genome.topology.max_cycles,
        "run_scout": genome.topology.use_scout,
        "genome_id": genome.id,
        "evolved": True,
    }
