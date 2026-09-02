"""Metrics endpoint for Prometheus scraping."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from maistro.observability.metrics import PROMETHEUS_CONTENT_TYPE, registry

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics() -> Response:
    """Expose application metrics for Prometheus scraping."""
    return Response(
        content=registry.render_prometheus(),
        media_type=PROMETHEUS_CONTENT_TYPE,
    )
