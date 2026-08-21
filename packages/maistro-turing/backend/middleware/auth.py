"""Auth for the Turing backend — two distinct lanes.

1. Human / admin lane: a session cookie, adapted from hive-conductor's
   middleware/auth.py. Humans view the dashboard, read the feed, chat with
   Turing, and (admins only) mutate self-model variables.

2. Turing-internal lane: a narrowly-scoped B2B service key from maistro.auth.
   Turing's own reactor/producers authenticate with this to post producer
   artifacts and write self-model updates back through the API — NOT general
   admin power. The scope list is fixed below and enforced per-route.

The middleware only establishes identity (cookie → user, service key →
ServiceIdentity) and rejects unauthenticated /v1 traffic. Per-route gating
(admin-only, required service scopes) is done with the FastAPI dependencies in
this module so each route declares exactly what it needs.
"""

from __future__ import annotations

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from maistro.auth import Scope, ServiceKeyAuthProvider, ServiceKeyRegistry

logger = logging.getLogger("turing.auth_middleware")

# Scopes Turing's own internals are allowed to use against this API. Explicitly
# NOT admin/dashboard scopes — Turing posts producer artifacts and writes
# self-model updates, nothing more.
TURING_INTERNAL_SCOPES: frozenset[Scope] = frozenset(
    {
        Scope.TURING_CHAT,
        Scope.TURING_VAULT_READ,
        Scope.TURING_VAULT_WRITE,
    }
)

_PUBLIC_EXACT = frozenset(
    {
        "/",
        "/health",
        "/v1/auth/login",
        "/v1/auth/whoami",
        "/favicon.ico",
    }
)

_PUBLIC_PREFIXES = (
    "/docs",
    "/openapi",
    "/redoc",
)


class TuringAuthMiddleware(BaseHTTPMiddleware):
    """Resolve a human session cookie OR a Turing service key onto request.state.

    Leaves request.state.user / request.state.service unset when absent; the
    route dependencies decide whether that is acceptable.
    """

    def __init__(self, app: object, registry: ServiceKeyRegistry) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._provider = ServiceKeyAuthProvider(registry)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if request.method == "OPTIONS":
            return await call_next(request)
        if path in _PUBLIC_EXACT or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        request.state.user = self._get_user(request)
        request.state.service = self._get_service(request)

        if path.startswith("/v1/") and request.state.user is None and request.state.service is None:
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})

        return await call_next(request)

    def _get_user(self, request: Request) -> dict | None:
        session_id = request.cookies.get("turing_session")
        if not session_id:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer ") and not auth.startswith("Bearer sk-svc-"):
                session_id = auth[7:]
        if not session_id:
            return None
        from ..routes.auth import get_current_user

        return get_current_user(session_id)

    def _get_service(self, request: Request):  # type: ignore[no-untyped-def]
        try:
            return self._provider.authenticate(dict(request.headers))
        except Exception:
            logger.warning("service key authentication error", exc_info=True)
            return None


# --------------------------------------------------------------- dependencies --


def require_user(request: Request) -> dict:
    """Human session required (any role)."""
    user = getattr(request.state, "user", None)
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Human session required")
    return user


def require_admin(request: Request) -> dict:
    """Human session with the admin role required."""
    user = require_user(request)
    if user.get("role") != "admin":
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def require_user_or_turing_scope(*scopes: Scope):  # type: ignore[no-untyped-def]
    """Accept either a human session or a Turing service key holding `scopes`.

    For read routes that both humans (the dashboard) and machine callers (the
    Astro build-time content loader, authenticating with TURING_BUILD_KEY) need
    to hit — `require_user` alone 401s a valid service key with no cookie.
    """
    over_broad = [s for s in scopes if s not in TURING_INTERNAL_SCOPES]
    if over_broad:
        raise ValueError(f"scopes outside Turing-internal allowlist: {over_broad}")

    def _dep(request: Request):  # type: ignore[no-untyped-def]
        from fastapi import HTTPException

        user = getattr(request.state, "user", None)
        if user is not None:
            return user

        service = getattr(request.state, "service", None)
        if service is None:
            raise HTTPException(
                status_code=401, detail="Human session or Turing service key required"
            )
        missing = [s.value for s in scopes if not service.has_scope(s)]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Missing Turing scopes: {', '.join(missing)}",
            )
        return service

    return _dep


def require_turing_scope(*scopes: Scope):  # type: ignore[no-untyped-def]
    """Service-key dependency factory — require Turing-internal scopes.

    Every requested scope must be in the fixed TURING_INTERNAL_SCOPES allowlist
    (defensive: a route cannot accidentally demand a broader scope) AND be held
    by the authenticated service identity.
    """
    over_broad = [s for s in scopes if s not in TURING_INTERNAL_SCOPES]
    if over_broad:
        raise ValueError(f"scopes outside Turing-internal allowlist: {over_broad}")

    def _dep(request: Request):  # type: ignore[no-untyped-def]
        from fastapi import HTTPException

        service = getattr(request.state, "service", None)
        if service is None:
            raise HTTPException(status_code=401, detail="Turing service key required")
        missing = [s.value for s in scopes if not service.has_scope(s)]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Missing Turing scopes: {', '.join(missing)}",
            )
        return service

    return _dep
