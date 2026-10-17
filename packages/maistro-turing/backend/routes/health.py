"""Liveness and readiness probes.

``/health`` is unconditional liveness. ``/health/ready`` reports whether a
governed Turing service identity is configured (#858): the backend refuses to
start without one, so the 503 branch covers a degenerate registry (for example
an operator probing a process whose identity configuration was revoked before
restart). Unavailability is reported, never silently served.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..config import service_identity_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "turing-backend"}


@router.get("/health/ready", response_model=None)
def ready(request: Request) -> dict | JSONResponse:
    registry = getattr(request.app.state, "turing_service_registry", None)
    configured, detail = service_identity_status(registry)
    if not configured:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "reason": detail},
        )
    return {"status": "ok", "service": "turing-backend", "service_identity": detail}
