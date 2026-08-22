"""Run the daily-status graph and shape the result for the Daily Report frontend.

The Hive registry still stores the historical editable DAG snapshot format.
This boundary executes the registered descriptor through the shared
``services.dag_agents`` path — canonical GraphTemplate instantiation with
``TemplateProvenance``, durable Run/NodeRun persistence — and translates the
result back into the response shape DailyReport.tsx already consumes.

Per-request Jira credentials are overlaid on the *instantiated* Graph, after
provenance is stamped: the template's content hash is provenance and must stay
secret-free.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from maistro.graph.definitions import Graph
from maistro.graph.durable_runs import RunStatus
from services.dag_agents import get_registry, run_registered_dag

logger = logging.getLogger(__name__)


# The current Hive Daily Report route predates Workspace/Project middleware and
# can still invoke this service without either scope id. The store used here is
# per-request and in-memory, so this explicit compatibility scope cannot leak
# durable records across users. Callers that have canonical ids should pass
# them; Project middleware can remove this fallback when it lands.
_FALLBACK_SCOPE_ID = "hive:daily-status"


def _get_registry() -> Any:
    """The shared DAG-as-agent registry (kept as this module's historical name)."""
    return get_registry()


def _node_named(graph: Graph, name: str) -> Any:
    """Look up an instantiated node by its stable editable name.

    ``GraphTemplate.instantiate`` assigns fresh node ids per Graph; the
    editable snapshot's ids survive as node *names*, which is the stable
    handle this boundary keys on.
    """
    return next((node for node in graph.nodes if node.name == name), None)


def _inject_jira_credentials(
    graph: Graph, *, pat: str, base_url: str, flavor: str = "server"
) -> Graph:
    """Overlay per-request Jira credentials onto the instantiated jira_poll node."""
    node = _node_named(graph, "jira_poll")
    if node is not None:
        node.inputs.update({"pat": pat, "base_url": base_url, "flavor": flavor})
    return graph


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
    resolved_project_id = project_id or _FALLBACK_SCOPE_ID
    resolved_workspace_id = workspace_id or resolved_project_id

    try:
        graph, result = await run_registered_dag(
            "daily-status",
            workspace_id=resolved_workspace_id,
            project_id=resolved_project_id,
            user_id=user_id,
            configure=lambda graph: _inject_jira_credentials(
                graph, pat=pat, base_url=base_url, flavor=flavor
            ),
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

    return _result_to_jira_section(result, graph=graph, base_url=base_url, flavor=flavor)


def _result_to_jira_section(
    result: Any,
    *,
    graph: Graph,
    base_url: str,
    flavor: str,
) -> dict[str, Any]:
    """Translate canonical Run/NodeRun state into the existing Jira response."""
    name_by_node_id = {node.node_id: node.name for node in graph.nodes}
    by_name = {name_by_node_id.get(nr.node_id, nr.node_id): nr for nr in result.node_runs}

    if result.status == RunStatus.FAILED:
        jp = by_name.get("jira_poll")
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

    jp_out = (by_name.get("jira_poll") or _missing()).result or {}
    filt_out = (by_name.get("jira_epic_filter") or _missing()).result or {}

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
