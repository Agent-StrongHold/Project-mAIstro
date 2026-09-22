"""Auth middleware — session cookies, role-based access, task-scoped elevation.

Public paths (setup, login, health, static) bypass auth.
Admin role is blocked from /v1/chat/ routes (break-glass only).
Protected ops require elevation bound to a task — permissions die with the task.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from config import get_settings, is_valid_oauth_provider_name
from fastapi import Request
from routes import auth as auth_routes
from routes import setup as setup_routes
from services import voice_identity
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from maistro.security.http_routes import load_route_policy, locate_route_registry, route_policy

logger = logging.getLogger("hive.auth_middleware")

#: Authenticated like everything else, but by a device credential rather than a
#: session — see `services/voice_identity.py`. This is not an exemption: with
#: no credential configured the prefix answers 401 like any other `/v1/` path.
_VOICE_PREFIX = "/v1/voice/"

# Documentation families are boundary-safe prefixes. The schema itself is
# one exact route so a future sibling such as /openapi-anything is protected.
_PUBLIC_PREFIXES = (
    "/v1/setup/",
    "/health",
    "/docs",
    "/redoc",
)

# Kept as an empty compatibility surface for route-gate fixtures; no loose
# public matching is permitted.
_PUBLIC_PREFIXES_LOOSE: tuple[str, ...] = ()
_OAUTH_PUBLIC_GET_RE = re.compile(r"^/v1/auth/oauth/(?P<provider>[^/]{1,128})/(?:start|callback)$")

_PUBLIC_EXACT = frozenset(
    {
        "/",
        "/v1/setup/status",
        "/v1/setup/presets",
        "/v1/auth/login",
        "/v1/auth/register",
        "/v1/auth/whoami",
        "/openapi.json",
        "/favicon.ico",
    }
)

_ADMIN_CHAT_BLOCKED = ("/v1/chat/",)


def _matches_public_prefix(path: str, prefix: str) -> bool:
    """True if path is exactly prefix, or prefix followed by '/'.

    Plain str.startswith() would also match unrelated sibling routes that
    merely share the prefix as a string (e.g. "/healthcheck-internal"
    starting with "/health"). Mirrors the boundary fix in
    tools/sandbox/workspace.py's path-prefix allowlist.
    """
    stripped = prefix.rstrip("/")
    return path == stripped or path.startswith(stripped + "/")


def _is_public_oauth_get(method: str, path: str) -> bool:
    """Expose only exact GET routes for providers enabled in typed settings."""
    if method != "GET":
        return False
    match = _OAUTH_PUBLIC_GET_RE.fullmatch(path)
    if match is None:
        return False
    provider = match.group("provider")
    if not is_valid_oauth_provider_name(provider):
        return False
    # SECURITY-REVIEW: This is the anonymous authentication boundary. A path
    # parameter is public only after exact syntax and configured-provider checks.
    return provider in get_settings().oauth_providers


def resolve_principal(
    cookies: Mapping[str, str], authorization: str | None
) -> dict[str, Any] | None:
    session_id = cookies.get("hive_session")
    if not session_id:
        auth_header = authorization or ""
        if auth_header.startswith("Bearer "):
            session_id = auth_header[7:]
    if not session_id:
        return None
    try:
        return auth_routes.get_current_user(session_id)
    except Exception:
        return None


def principal_has_permission(user: dict[str, Any], perm: str) -> bool:
    if user.get("role") == "admin":
        return True
    user_perms = user.get("permissions", [])
    if perm not in user_perms:
        return False
    elevated = user.get("elevated_permissions", [])
    return perm in elevated


def origin_allowed(origin: str | None, host: str | None = None) -> bool:
    """Is `origin` permitted to open a credentialed connection to this server?

    Three ways to pass, in order of how often they matter:

    1. **Same-origin.** The page that opened the socket is served by this very
       server (`Origin`'s authority == the request's own `Host`). CORS never
       applies to same-origin requests, so a deployment reached at
       `http://192.0.2.1:8101` — where the SPA and the API share an origin —
       has never had any reason to list itself in `CORS_ORIGINS`, and most
       don't. Checking the configured list alone would reject the app's own
       front end on every non-localhost deployment, because the defaults in
       `config.py` only cover localhost.
    2. **No Origin at all.** curl and other non-browser callers send none.
       Origin-based rules only bind browsers; such a caller still needs a valid
       session.
    3. **Explicitly configured**, including the `"*"` wildcard that
       `CORSMiddleware` already honours for HTTP. Not honouring it here would
       mean a deployment that deliberately opened CORS still had its sockets
       refused.
    """
    if not origin:
        return True
    allowed = get_settings().cors_origins
    if "*" in allowed or origin in allowed:
        return True

    if host:
        _, _, origin_authority = origin.partition("://")
        if origin_authority and origin_authority == host:
            return True

    return False


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        # Resolved from this file's real location so both the monorepo checkout
        # and the packaged image (backend at /app/backend, registry at
        # /app/quality) find the reviewed declarations. A missing registry
        # fails closed here instead of serving an unclassified surface.
        self._route_policy = load_route_policy(locate_route_registry(Path(__file__)), "conductor")

    async def dispatch(  # noqa: C901
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if request.method == "OPTIONS":
            return await call_next(request)

        policy = route_policy(self._route_policy, request.method, path)
        public_path = (
            path in _PUBLIC_EXACT
            or _is_public_oauth_get(request.method, path)
            or any(_matches_public_prefix(path, p) for p in _PUBLIC_PREFIXES)
        )
        if public_path:
            if (policy is None or policy.get("access") != "public") and path not in {
                "/",
                "/favicon.ico",
            }:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Route authorization declaration required"},
                )
            return await call_next(request)

        # The declaration gate covers the HTTP API. Non-API paths include the
        # product's static SPA fallback, which has its own public serving
        # boundary and is not a principal-bearing backend route.
        if policy is None:
            if not path.startswith("/v1/"):
                return await call_next(request)
            return JSONResponse(
                status_code=403,
                content={"detail": "Route authorization declaration required"},
            )

        # The install wizard API is only useful before first-run provisioning,
        # when no account exists yet to authenticate with. Public pre-setup;
        # normal auth applies once setup completes (same one-shot boundary as
        # /v1/setup/complete's 409 guard).
        if _matches_public_prefix(path, "/v1/install/") and not self._setup_complete():
            return await call_next(request)

        user = self._get_user(request)
        if user is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
        request.state.user = user

        if user["role"] == "admin" and self._is_chat(path):
            return JSONResponse(
                status_code=403,
                content={"detail": "Admin account cannot use chat. Use your daily user account."},
            )

        # Persona-level feedback aggregates raw entries across all workspaces
        # using that persona. A normal workspace member may not inspect other
        # workspaces' user ids, comments, or identifiers.
        if (
            request.method == "GET"
            and path.startswith("/v1/workspaces/persona-templates/")
            and path.endswith("/feedback")
            and user.get("role") != "admin"
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "Admin permission required for persona-wide feedback"},
            )

        required_perm = self._required_permission(request)
        if required_perm and not self._check_permission(user, required_perm):
            return JSONResponse(
                status_code=403,
                content={"detail": f"Permission '{required_perm}' required. Elevate to proceed."},
            )

        return await call_next(request)

    def _setup_complete(self) -> bool:
        try:
            return bool(setup_routes._is_setup_complete())
        except Exception:
            # Fail closed: if setup state can't be read, require auth.
            return True

    def _get_user(self, request: Request) -> dict[str, Any] | None:
        authorization = request.headers.get("Authorization")
        user = resolve_principal(request.cookies, authorization)
        if user is not None:
            return user
        # Scoped to the voice prefix on purpose. Resolving the device
        # credential for every path would make one key a second way into the
        # whole API; here it opens the surface it was issued for and nothing
        # else, and a caller holding it still gets that account's own
        # authorization for everything downstream.
        if _matches_public_prefix(request.url.path, _VOICE_PREFIX):
            return voice_identity.principal_for(authorization)
        return None

    def _is_chat(self, path: str) -> bool:
        return any(path.startswith(p) for p in _ADMIN_CHAT_BLOCKED)

    def _required_permission(self, request: Request) -> str | None:
        """Return the permission declared for this exact registered route."""
        policy = route_policy(self._route_policy, request.method, request.url.path)
        if policy is None or policy.get("access") != "permission":
            return None
        permission = policy.get("permission")
        return permission if isinstance(permission, str) else None

    def _check_permission(self, user: dict[str, Any], perm: str) -> bool:
        return principal_has_permission(user, perm)
