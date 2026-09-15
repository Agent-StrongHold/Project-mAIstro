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
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from maistro.auth import Scope, ServiceKeyAuthProvider, ServiceKeyRegistry, canonical_permission
from maistro.security.http_routes import load_route_policy, matches_prefix, route_policy
from maistro.security.sentinel.authz_types import Principal

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
        "/openapi.json",
        "/favicon.ico",
    }
)

_PUBLIC_PREFIXES = (
    "/docs",
    "/redoc",
)

# Route declarations are shared with the CI gate. The backend refuses to serve
# a protected path that is absent from this reviewed table; CI remains the
# earlier feedback loop, while this branch is the runtime default-deny floor.
_ROUTE_REGISTRY = Path(__file__).resolve().parents[4] / "quality" / "route-permissions.json"


class TuringAuthMiddleware(BaseHTTPMiddleware):
    """Resolve a human session cookie OR a Turing service key onto request.state.

    Leaves request.state.user / request.state.service unset when absent; the
    route dependencies decide whether that is acceptable.
    """

    def __init__(self, app: object, registry: ServiceKeyRegistry) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._provider = ServiceKeyAuthProvider(registry)
        self._route_policy = load_route_policy(_ROUTE_REGISTRY, "turing")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if request.method == "OPTIONS":
            return await call_next(request)
        if path in _PUBLIC_EXACT or any(matches_prefix(path, p) for p in _PUBLIC_PREFIXES):
            # The route table is authoritative for every registered public
            # family, not only /v1. Keep the historical synthetic /favicon and
            # root declarations usable when FastAPI has no matching route.
            policy = route_policy(self._route_policy, request.method, path)
            if policy is None and path not in {"/", "/favicon.ico"}:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Route authorization declaration required"},
                )
            if policy is not None and policy.get("access") != "public":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Route authorization declaration required"},
                )
            return await call_next(request)
        request.state.user = self._get_user(request)
        request.state.service = self._get_service(request)

        if request.state.user is None and request.state.service is None:
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
        policy = route_policy(self._route_policy, request.method, path)
        if policy is None:
            return JSONResponse(
                status_code=403,
                content={"detail": "Route authorization declaration required"},
            )
        if policy.get("access") == "permission" and not self._has_permission(
            policy.get("permission"), request
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": f"Permission '{policy.get('permission')}' required"},
            )

        return await call_next(request)

    def _has_permission(self, permission: object, request: Request) -> bool:
        if not isinstance(permission, str):
            return False
        principal = self._principal(request)
        if principal is None:
            return False
        # Dependencies remain the authority for service-key route semantics
        # (including the human-only admin lane). The declaration gate still
        # requires every path to name its canonical permission, but it must not
        # replace those product-specific checks.
        if principal.kind == "agent":
            return True
        # Publishing is still owned by the existing dependency for human
        # callers rather than changing that product authorization lane here.
        if principal.kind == "human" and permission == "turing.vault_write":
            return True
        # The route table and Principal.scopes use the same scope.verb action
        # names. There is no Turing-only permission translation or allow-on-miss.
        return principal.roles == ("admin",) or permission in principal.scopes

    @staticmethod
    def _principal(request: Request) -> Principal | None:
        user = getattr(request.state, "user", None)
        if user is not None:
            return Principal(
                id=str(user.get("id", "unknown")),
                kind="human",
                roles=(str(user.get("role", "")),),
                scopes=tuple(str(scope) for scope in user.get("scopes", ())),
            )
        service = getattr(request.state, "service", None)
        if service is None:
            return None
        # ServiceKeyRegistry's transport contract is Scope's colon spelling;
        # Principal is the canonical authorization contract used by policy.
        scopes = tuple(canonical_permission(scope) for scope in service.scopes)
        return Principal(
            id=f"service:{service.name}",
            kind="agent",
            scopes=scopes,
            owner="system",
        )

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
