"""Run the daily-status graph and shape the result for the Daily Report frontend.

The Hive registry still stores the historical editable DAG snapshot format. At
this application boundary we convert that snapshot into the canonical Graph
model, inject per-request Jira credentials, execute it through the canonical
durable Run/NodeRun persistence path, and translate the result back into the
response shape DailyReport.tsx already consumes.

The legacy inline polling stays as a fallback for the case where the substrate
is unavailable or the run fails. Graceful degradation matters for an
observability surface.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from maistro.container import build_node_resolver
from maistro.graph.dag_registry import DagRegistry
from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus, run_durable_graph
from maistro.graph.seeds import daily_status_seed

logger = logging.getLogger(__name__)


# Module-level registry so a per-process boot registers once + reuses.
_registry: DagRegistry | None = None

# Module-level resolver: this app imports maistro-core pieces directly rather
# than constructing a full Container, so build_node_resolver()'s no-arg
# defaults (the shared usage log, an empty harness-adapter map) are what it
# picks up. The resolver receives the canonical Graph from run_durable_graph.
_node_resolver = build_node_resolver()

# The current Hive Daily Report route predates Workspace/Project middleware and
# can still invoke this service without either scope id. The store used here is
# per-request and in-memory, so this explicit compatibility scope cannot leak
# durable records across users. Callers that have canonical ids should pass
# them; Project middleware can remove this fallback when it lands.
_FALLBACK_SCOPE_ID = "hive:daily-status"


def _get_registry() -> DagRegistry:
    """Lazily build the DagRegistry + register the bundled seeds."""
    global _registry
    if _registry is None:
        _registry = DagRegistry()
        _registry.register(daily_status_seed())
    return _registry


def _inject_jira_credentials(
    dag: dict[str, Any], *, pat: str, base_url: str, flavor: str = "server"
) -> dict[str, Any]:
    """Overlay per-request Jira credentials onto a copied registry snapshot."""
    for spec in dag.get("nodes", []):
        if spec.get("id") == "jira_poll":
            inputs = dict(spec.get("inputs", {}))
            inputs["pat"] = pat
            inputs["base_url"] = base_url
            inputs["flavor"] = flavor
            spec["inputs"] = inputs
            break
    return dag


def _canonical_graph_from_snapshot(
    snapshot: dict[str, Any],
    *,
    workspace_id: str | None,
    project_id: str | None,
) -> Graph:
    """Project the editable DagRegistry snapshot into the canonical Graph model."""
    resolved_project_id = project_id or _FALLBACK_SCOPE_ID
    resolved_workspace_id = workspace_id or resolved_project_id

    nodes: list[Node] = []
    for raw in snapshot.get("nodes", []):
        node_id = str(raw.get("id") or "")
        node_type = str(raw.get("kind") or "")
        metadata = {
            key: value
            for key, value in raw.items()
            if key not in {"id", "kind", "name", "config", "inputs", "outputs"}
        }
        nodes.append(
            Node(
                node_id=node_id,
                node_type=node_type,
                name=str(raw.get("name") or node_id),
                parameters=dict(raw.get("config") or {}),
                inputs=dict(raw.get("inputs") or {}),
                outputs=dict(raw.get("outputs") or {}),
                metadata=metadata,
            )
        )

    edges: list[Edge] = []
    for index, raw in enumerate(snapshot.get("edges", []), start=1):
        from_node = str(raw.get("from_node") or raw.get("from_role") or "")
        to_node = str(raw.get("to_node") or raw.get("to_role") or "")
        metadata = {
            key: value
            for key, value in raw.items()
            if key
            not in {"id", "edge_id", "from_node", "from_role", "to_node", "to_role", "condition"}
        }
        edges.append(
            Edge(
                edge_id=str(raw.get("edge_id") or raw.get("id") or f"edge-{index}"),
                from_node=from_node,
                to_node=to_node,
                condition=raw.get("condition"),
                metadata=metadata,
            )
        )

    entry_node = snapshot.get("entry_node") or snapshot.get("entry")
    graph_metadata = {
        key: value
        for key, value in snapshot.items()
        if key not in {"id", "name", "description", "nodes", "edges", "entry_node", "entry"}
    }
    if entry_node is not None:
        graph_metadata["entry_node"] = str(entry_node)

    return Graph(
        graph_id=str(snapshot.get("id") or "daily-status"),
        workspace_id=resolved_workspace_id,
        project_id=resolved_project_id,
        name=str(snapshot.get("name") or "Daily Status"),
        description=str(snapshot.get("description") or ""),
        nodes=nodes,
        edges=edges,
        metadata=graph_metadata,
    )


async def run_daily_status_dag(
    *,
    user_id: str | None,
    project_id: str | None,
    pat: str,
    base_url: str,
    flavor: str = "server",
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Run daily status and return the Jira section shape used by the frontend."""
    registry = _get_registry()
    snapshot = dict(registry.get("daily-status").snapshot)
    snapshot["nodes"] = [dict(n) for n in snapshot["nodes"]]
    _inject_jira_credentials(snapshot, pat=pat, base_url=base_url, flavor=flavor)
    graph = _canonical_graph_from_snapshot(
        snapshot,
        workspace_id=workspace_id,
        project_id=project_id,
    )

    store = InMemoryDurableRunStore()
    try:
        result = await run_durable_graph(
            graph,
            store=store,
            node_resolver=_node_resolver,
            actor_principal_id=user_id,
        )
    except Exception as exc:
        logger.warning("daily_status_dag_run_failed: %s", exc)
        return {
            "status": "error",
            "detail": f"daily-status DAG run raised: {type(exc).__name__}",
            "issues": [],
            "source": "dag:daily-status",
        }

    try:
        from services.node_metrics_store import record_run_completion

        record_run_completion(result)
    except Exception as exc:
        logger.warning("daily_status_metrics_ingest_failed: %s", exc)

    return _result_to_jira_section(result, base_url=base_url, flavor=flavor)


def _result_to_jira_section(
    result: Any,
    *,
    base_url: str,
    flavor: str,
) -> dict[str, Any]:
    """Translate canonical Run/NodeRun state into the existing Jira response."""
    by_id = {nr.node_id: nr for nr in result.node_runs}

    if result.status == RunStatus.FAILED:
        jp = by_id.get("jira_poll")
        jp_error = str(getattr(jp, "error", "") or "")
        if jp_error.startswith("PermissionError:"):
            detail = jp_error.partition(":")[2].strip() or "Jira authentication failed"
            return {
                "status": "auth_failed",
                "detail": detail,
                "issues": [],
                "source": "dag:daily-status",
            }
        run_error = str(getattr(getattr(result, "run", None), "error", "") or "")
        return {
            "status": "error",
            "detail": run_error or "daily-status run failed",
            "issues": [],
            "source": "dag:daily-status",
        }

    jp_out = (by_id.get("jira_poll") or _missing()).result or {}
    filt_out = (by_id.get("jira_epic_filter") or _missing()).result or {}

    issues = []
    for raw in jp_out.get("issues") or []:
        issues.append(
            {
                "key": raw.get("key", ""),
                "summary": raw.get("summary", ""),
                "status": raw.get("status", ""),
                "updated": raw.get("updated", ""),
                "url": raw.get("url", f"{base_url.rstrip('/')}/browse/{raw.get('key', '')}"),
            }
        )

    return {
        "status": "ok",
        "issues": issues,
        "count": int(jp_out.get("count") or 0),
        "epics_kept": int(filt_out.get("kept") or 0),
        "source": "dag:daily-status",
        "flavor": flavor,
    }


class _MissingNode:
    """None-safe sentinel for optional canonical NodeRun lookups."""

    result: ClassVar[dict[str, Any]] = {}


def _missing() -> _MissingNode:
    return _MissingNode()
