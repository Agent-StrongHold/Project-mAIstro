"""Metrics endpoint for Prometheus scraping."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from maistro.observability.metrics import registry

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics() -> JSONResponse:
    """Expose application metrics in JSON format for monitoring."""
    return JSONResponse(content=registry.collect_all())
