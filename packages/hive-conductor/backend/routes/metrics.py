"""Phase 5 — Signal #5 endpoints.

  GET /v1/dag-runs/metrics
      Aggregate stats over a time window (default 1h). Query:
        ?node_kind=<kind>      filter to one node kind
        ?node_id=<id>          filter to one node by id
        ?project_id=<id>       filter to one project
        ?dag_id=<id>           filter to one saved DAG
        ?window_seconds=3600   sliding window

  GET /v1/dag-runs/metrics/observations
      Recent raw observations (for the optimizer + UI debug). Same
      filters; `limit` caps the list size (default 100).

Auth: AuthMiddleware. Read-only — no audit entry needed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from services.node_metrics_store import get_store

router = APIRouter(tags=["dag-metrics"])


@router.get("")
def aggregate_metrics(
    node_kind: str = "",
    node_id: str = "",
    project_id: str = "",
    dag_id: str = "",
    window_seconds: int = 3600,
) -> dict[str, Any]:
    return get_store().aggregate(
        node_kind=node_kind,
        node_id=node_id,
        project_id=project_id,
        dag_id=dag_id,
        window_seconds=max(60, min(window_seconds, 7 * 24 * 3600)),
    )


@router.get("/observations")
def list_observations(
    node_kind: str = "",
    project_id: str = "",
    window_seconds: int = 3600,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return get_store().list_observations(
        node_kind=node_kind,
        project_id=project_id,
        window_seconds=max(60, min(window_seconds, 7 * 24 * 3600)),
        limit=max(1, min(limit, 1000)),
    )
