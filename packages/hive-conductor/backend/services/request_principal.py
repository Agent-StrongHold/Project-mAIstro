"""Read the canonical HTTP principal from a FastAPI request (P0.1 / AC-P1)."""

from __future__ import annotations

from fastapi import HTTPException, Request

from maistro.identity import Principal


def request_principal(request: Request) -> Principal | None:
    """Return the principal AuthMiddleware attached, or None."""
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal
    return None


def require_principal(request: Request) -> Principal:
    """Return the authenticated principal or refuse the request."""
    principal = request_principal(request)
    if principal is None or not principal.actor_id():
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


def require_actor_id(request: Request) -> str:
    """Return the authenticated actor id or refuse the request."""
    return require_principal(request).actor_id()


def optional_actor_id(request: Request, *, default: str = "") -> str:
    """Return the actor id when present, otherwise ``default``."""
    principal = request_principal(request)
    if principal is None:
        return default
    return principal.actor_id() or default
