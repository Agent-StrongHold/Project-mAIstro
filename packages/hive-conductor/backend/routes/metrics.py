"""Phase 5 — Signal #5 endpoints.

  GET /v1/dag-metrics
      Aggregate stats over a time window (default 1h). Query:
        ?node_kind=<kind>      filter to one node kind
        ?node_id=<id>          filter to one node by id
        ?project_id=<id>       filter to one project
        ?dag_id=<id>           filter to one saved DAG
        ?window_seconds=3600   sliding window

  GET /v1/dag-metrics/observations
      Recent raw observations (for the optimizer + UI debug). Same
      filters; `limit` caps the list size (default 100).

  GET /v1/dag-metrics/retention
      Deployment-level retention description. No per-row data, so no
      principal is read (the same rule `/v1/dag-runs/retention` set).

Auth: AuthMiddleware authenticates; the two data-bearing routes authorize
at the caller's canonical Workspace boundary (#1174) — the same door
`routes/dag_runs.py` reads through (`services.dag_run_inspection`). An
observation written in a Workspace the caller cannot inspect is
indistinguishable from one that does not exist, and an observation that
names no Workspace is served to no HTTP reader at all (fail-closed, like
an unscoped run row). Read-only — no audit entry needed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from services.dag_run_inspection import authorized_workspace_ids
from services.node_metrics_store import get_store

router = APIRouter(tags=["dag-metrics"])


def _user_id(request: Request) -> str:
    """Principal for this request — set by AuthMiddleware on every /v1/ path.

    The explicit refusal mirrors routes/dag_runs.py: a handler that cannot
    name its principal must fail closed rather than guess, because every
    response below is scoped to that principal's Workspace universe.
    """
    user = getattr(request.state, "user", None) or {}
    uid = str(user.get("id") or user.get("username") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uid


@router.get("/retention")
def retention() -> dict[str, Any]:
    """State the observation bound and whether this deployment persists it.

    Observations are a query projection, not an execution ledger. The oldest
    rows are deleted automatically when the bound is reached; this API has no
    ad-hoc deletion operation because canonical Run retention owns execution
    deletion and replaying a completion can rebuild a projection row.
    """
    from services.node_metrics_store import DEFAULT_MAX_OBSERVATIONS, get_store

    store = get_store()
    return {
        "durable": store.is_durable,
        "max_observations": DEFAULT_MAX_OBSERVATIONS,
        "window_seconds_default": 3600,
        "max_window_seconds": 7 * 24 * 3600,
        "deletion": "oldest observations are evicted at max_observations; no ad-hoc delete",
    }


@router.get("")
async def aggregate_metrics(
    request: Request,
    node_kind: str = "",
    node_id: str = "",
    project_id: str = "",
    dag_id: str = "",
    window_seconds: int = 3600,
) -> dict[str, Any]:
    allowed = await authorized_workspace_ids(_user_id(request))
    return get_store().aggregate(
        node_kind=node_kind,
        node_id=node_id,
        project_id=project_id,
        dag_id=dag_id,
        window_seconds=max(60, min(window_seconds, 7 * 24 * 3600)),
        workspace_ids=allowed,
    )


@router.get("/observations")
async def list_observations(
    request: Request,
    node_kind: str = "",
    project_id: str = "",
    window_seconds: int = 3600,
    limit: int = 100,
) -> list[dict[str, Any]]:
    allowed = await authorized_workspace_ids(_user_id(request))
    return get_store().list_observations(
        node_kind=node_kind,
        project_id=project_id,
        window_seconds=max(60, min(window_seconds, 7 * 24 * 3600)),
        workspace_ids=allowed,
        limit=max(1, min(limit, 1000)),
    )
