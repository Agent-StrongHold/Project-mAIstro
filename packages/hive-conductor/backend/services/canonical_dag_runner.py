"""Canonical execution adapter for Hive's legacy stored DAG shape.

The stored/UI DAG schemas predate canonical ``Graph`` definitions. This module
normalizes those definitions and hands all traversal, concurrency,
NodeRun/Attempt creation, failure folding, and terminal-state authority to
``run_durable_graph``. Only one-node compatibility behavior remains outside the
canonical executor.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from typing import Any

from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import (
    RunStatus,
    recover_queued_graph_runs,
    resume_due_graph_runs,
    run_durable_graph,
)
from maistro.graph.types import DEFAULT_SYSTEM_PROMPTS, JSON_OUTPUT_SCHEMAS, AgentRole
from maistro.runs.model import TERMINAL_RUN_STATUSES, Run
from services.dag_agents import _container, get_run_store
from services.legacy_dag_node import LegacyConductorNode, OnResponseHook
from services.node_metrics_store import record_run_completion

logger = logging.getLogger(__name__)
_COMPAT_SCOPE = "hive-standalone-compat"
_SCOUT_NODE_ID = "__hive_legacy_scout__"
_SCOUT_EDGE_ID = "__hive_legacy_scout_to_entry__"
# These are historical evolution tokens, not expressions in the canonical
# predicate language. The shipped dependency-wave runner ignored edge
# conditions entirely, so treating them as predicates would silently skip work
# that ran before convergence. Preserve that behavior while retaining the token
# as provenance on the canonical edge.
_LEGACY_DEPENDENCY_CONDITIONS = frozenset({"success", "failure", "timeout"})


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


def _edge_endpoints(raw: Mapping[str, Any]) -> tuple[str, Any]:
    """Normalize both shipped edge dialects.

    The CRUD route stores ``from_node``/``to_node`` while substrate-created
    workflows historically store ``source``/``target``. Both are product data,
    so convergence must read both without preserving two execution engines.
    """
    src = raw.get("from_node") if "from_node" in raw else raw.get("source")
    dst = raw.get("to_node") if "to_node" in raw else raw.get("target")
    return str(src or "").strip(), dst


def _raw_edges(dag_data: Mapping[str, Any], node_ids: set[str]) -> list[dict[str, Any]]:
    edges = dag_data.get("edges", [])
    if not isinstance(edges, list):
        raise ValueError("DAG edges must be a list")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(edges):
        if not isinstance(raw, Mapping):
            raise ValueError("DAG edge must be an object")
        src, dst_value = _edge_endpoints(raw)
        # Evolution genomes historically use a null destination as a terminal
        # marker. It does not represent a dependency edge in the canonical DAG.
        if dst_value in (None, ""):
            continue
        dst = str(dst_value).strip()
        if src not in node_ids or dst not in node_ids:
            raise ValueError(
                f"edge {raw.get('id', index)!r} references node outside DAG: {src!r}->{dst!r}"
            )
        normalized.append(
            {
                **dict(raw),
                "id": str(raw.get("id") or f"{src}->{dst}"),
                "from_node": src,
                "to_node": dst,
            }
        )
    return normalized


def _entry_node(
    dag_data: Mapping[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> str:
    explicit = str(dag_data.get("entry_node") or "").strip()
    ids = {str(node["id"]) for node in nodes}
    if explicit:
        if explicit not in ids:
            raise ValueError(f"DAG entry node {explicit!r} does not exist")
        return explicit
    incoming = {str(edge["to_node"]) for edge in edges}
    roots = [str(node["id"]) for node in nodes if str(node["id"]) not in incoming]
    if len(roots) == 1:
        return roots[0]
    if not roots:
        # The cycle validator below will emit the more useful diagnosis.
        return str(nodes[0]["id"])
    raise ValueError(
        "DAG has multiple disconnected entry roots; choose one entry_node or connect the graph: "
        + ", ".join(roots)
    )


def _validate_acyclic_and_reachable(
    entry: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    adjacency: dict[str, list[str]] = {str(node["id"]): [] for node in nodes}
    indegree: dict[str, int] = dict.fromkeys(adjacency, 0)
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


def _legacy_scout_node() -> dict[str, Any]:
    """Represent the old pre-entry Scout as ordinary canonical physical work."""
    return {
        "id": _SCOUT_NODE_ID,
        "name": "Scout",
        "role": AgentRole.SCOUT.value,
        "prompt": DEFAULT_SYSTEM_PROMPTS[AgentRole.SCOUT]
        + JSON_OUTPUT_SCHEMAS.get(AgentRole.SCOUT, ""),
        "config": {"execution_tier": "safe"},
        "compat_synthetic": "legacy_run_scout",
    }


def _execution_shape(
    dag_data: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Return validated nodes, dependency edges, and canonical entry.

    ``run_scout`` used to execute a Scout NodeRun before the configured entry.
    It is represented as a synthetic canonical node rather than being ignored
    or run out-of-band, so it gets the same Run/NodeRun/Attempt provenance as
    every other physical step.
    """
    nodes = _raw_nodes(dag_data)
    node_ids = {str(node["id"]) for node in nodes}
    if _SCOUT_NODE_ID in node_ids:
        raise ValueError(f"DAG node id {_SCOUT_NODE_ID!r} is reserved for run_scout compatibility")
    edges = _raw_edges(dag_data, node_ids)
    entry = _entry_node(dag_data, nodes, edges)
    _validate_acyclic_and_reachable(entry, nodes, edges)
    if not dag_data.get("run_scout"):
        return nodes, edges, entry

    scout = _legacy_scout_node()
    scout_edge = {
        "id": _SCOUT_EDGE_ID,
        "from_node": _SCOUT_NODE_ID,
        "to_node": entry,
        "condition": None,
        "compat_synthetic": "legacy_run_scout",
    }
    return [scout, *nodes], [scout_edge, *edges], _SCOUT_NODE_ID


def _canonical_condition(raw: Mapping[str, Any]) -> str | None:
    """Translate a legacy edge condition without inventing new routing semantics."""
    value = raw.get("condition")
    if value is None:
        return None
    condition = str(value).strip()
    if not condition or condition.lower() in _LEGACY_DEPENDENCY_CONDITIONS:
        return None
    return condition


def _edge_metadata(raw: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {"parallel": True, "legacy_dependency_edge": True}
    if raw.get("condition") not in (None, ""):
        metadata["legacy_condition"] = str(raw["condition"])
    if raw.get("compat_synthetic"):
        metadata["compat_synthetic"] = str(raw["compat_synthetic"])
    return metadata


def graph_from_legacy_dag(
    dag_data: Mapping[str, Any], *, workspace_id: str, project_id: str
) -> Graph:
    """Translate one shipped legacy DAG into an immutable canonical Graph."""
    nodes, raw_edges, entry = _execution_shape(dag_data)

    graph_nodes = [
        Node(
            node_id=str(raw["id"]),
            node_type="hive.legacy_node",
            name=str(raw.get("name") or raw["id"]),
            metadata={
                "role": str(raw.get("role") or "worker"),
                "legacy_node": dict(raw),
                **(
                    {"compat_synthetic": str(raw["compat_synthetic"])}
                    if raw.get("compat_synthetic")
                    else {}
                ),
            },
        )
        for raw in nodes
    ]
    graph_edges = [
        Edge(
            edge_id=str(raw["id"]),
            from_node=str(raw["from_node"]),
            to_node=str(raw["to_node"]),
            condition=_canonical_condition(raw),
            # Legacy edges are dependency edges. Marking each selected edge as
            # parallel preserves fan-out while the canonical executor owns the
            # frontier, concurrency cap, fan-in readiness, and terminal state.
            metadata=_edge_metadata(raw),
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
            "legacy_run_scout": bool(dag_data.get("run_scout")),
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
) -> tuple[str, str, Any]:
    container = _container()
    if container is None:
        return (
            workspace_id or str(dag_data.get("workspace_id") or _COMPAT_SCOPE),
            project_id or str(dag_data.get("project_id") or _COMPAT_SCOPE),
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
    return resolved_workspace, resolved_project, container.run_store


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


def _recovery_resolver(run: Run):
    """Rebuild one legacy-node resolver entirely from durable canonical Run facts."""
    graph = run.graph.materialize()
    raw_by_id: dict[str, dict[str, Any]] = {}
    for node in graph.nodes:
        raw = node.metadata.get("legacy_node")
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"Run {run.run_id!r} node {node.node_id!r} lacks durable legacy_node metadata"
            )
        raw_by_id[node.node_id] = dict(raw)

    execution_mode = str(run.provenance.get("execution_mode") or "autonomous")
    if execution_mode not in {"interactive", "autonomous"}:
        raise ValueError(f"Run {run.run_id!r} has invalid legacy execution_mode {execution_mode!r}")
    legacy_dag_id = str(graph.metadata.get("legacy_dag_id") or graph.graph_id)
    return _resolver(
        raw_by_id,
        task_desc=graph.description or graph.name,
        node_env=_node_env(
            {"id": legacy_dag_id},
            user_id=run.actor_principal_id or "",
            # Never persist request-time credential values into Run/Graph
            # provenance. The legacy adapter did not consume USER_CRED_* keys;
            # durable recovery reuses deployment credentials only.
            user_credentials=None,
        ),
        execution_mode=execution_mode,
        on_response=None,
        llm_builder=None,
    )


async def recover_stranded_dag_runs(*, limit: int = 100) -> int:
    """Recover only canonical Runs admitted by the shipped legacy DAG adapter."""
    container = _container()
    if container is None or container.graph_run_store is None:
        return 0
    return await recover_queued_graph_runs(
        store=container.graph_run_store,
        run_store=container.run_store,
        node_resolver_factory=_recovery_resolver,
        eligible=lambda run: run.provenance.get("admission_source") == "hive_legacy_dag",
        events=container.event_bus,
        limit=limit,
    )


async def wake_due_dag_runs(*, limit: int = 100) -> int:
    """Wake elapsed legacy-DAG timed waits through the canonical resume seam.

    The timed half of #837/#913 reachability: a durable legacy-DAG
    continuation parked WAITING with an elapsed ``resume_at`` is resumed from
    its own persisted Run facts, by the same ownership rule the bootstrap
    half uses. The resolver is rebuilt per Run because which legacy node
    implementation may execute is durable Run metadata, not state this
    process holds. Crash dispositions reach the Container's canonical Event
    bus exactly as ``recover_abandoned_attempts`` reports them (#62).
    """
    container = _container()
    if container is None or container.graph_run_store is None:
        return 0
    return await resume_due_graph_runs(
        store=container.graph_run_store,
        run_store=container.run_store,
        node_resolver_factory=_recovery_resolver,
        eligible=lambda run: run.provenance.get("admission_source") == "hive_legacy_dag",
        events=container.event_bus,
        limit=limit,
    )


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
        "annotations": dict(record.graph_state.blackboard_snapshot.get("node_annotations") or {}),
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
    """Run a shipped Hive DAG as one canonical durable Graph Run."""
    resolved_workspace, resolved_project, canonical_run_store = await _scope(
        dag_data,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    graph = graph_from_legacy_dag(
        dag_data,
        workspace_id=resolved_workspace,
        project_id=resolved_project,
    )
    execution_nodes, _, _ = _execution_shape(dag_data)
    raw_by_id = {str(raw["id"]): raw for raw in execution_nodes}
    task_desc = str(dag_data.get("description") or dag_data.get("name") or "")
    provenance = {
        "admission_source": "hive_legacy_dag",
        "legacy_dag_id": str(dag_data.get("id") or ""),
        "executor": "durable_graph",
        "execution_mode": execution_mode,
    }

    admitted_run_id = None
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
