"""Metrics endpoint for Prometheus scraping."""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response

from maistro.auth import Scope, ServiceKeyAuthProvider, ServiceKeyRegistry
from maistro.observability.metrics import PROMETHEUS_CONTENT_TYPE, registry

router = APIRouter(tags=["observability"])


@lru_cache(maxsize=1)
def _metrics_auth_provider() -> ServiceKeyAuthProvider:
    """Load the scraper identity from the canonical service-key registry."""
    service_keys = ServiceKeyRegistry()
    service_keys.load_all()
    return ServiceKeyAuthProvider(service_keys)


async def require_metrics_scope(request: Request) -> None:
    """Require a service identity explicitly scoped to read metrics.

    This deliberately does not accept the broader user/API-key authentication
    path: a scraper is a machine principal and should receive only the
    observability permission it needs. Forwarded headers are not consulted;
    proxy trust belongs to the deployment boundary, not this authorization
    decision.
    """
    identity = _metrics_auth_provider().authenticate(dict(request.headers))
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Metrics authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not identity.has_scope(Scope.METRICS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Metrics scope required",
        )


@router.get("/metrics", dependencies=[Depends(require_metrics_scope)])
async def metrics() -> Response:
    """Expose application metrics only to the scoped Prometheus scraper."""
    return Response(
        content=registry.render_prometheus(),
        media_type=PROMETHEUS_CONTENT_TYPE,
    )
