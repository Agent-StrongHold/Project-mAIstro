"""Auth middleware — session cookies, role-based access, task-scoped elevation.

Public paths (setup, login, health, static) bypass auth.
Admin role is blocked from /v1/chat/ routes (break-glass only).
Protected ops require elevation bound to a task — permissions die with the task.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from config import get_settings, is_valid_oauth_provider_name
from fastapi import Request
from routes import auth as auth_routes
from routes import setup as setup_routes
from services import authorization, voice_identity
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from maistro.identity import Principal

logger = logging.getLogger("hive.auth_middleware")

_PUBLIC_PREFIXES = (
    "/v1/setup/",
    "/health",
)

#: Authenticated like everything else, but by a device credential rather than a
#: session — see `services/voice_identity.py`. This is not an exemption: with
#: no credential configured the prefix answers 401 like any other `/v1/` path.
_VOICE_PREFIX = "/v1/voice/"

# FastAPI's default docs/openapi paths don't end in "/" (the real route is
# /openapi.json), so they can't use the boundary-safe prefix check below —
# keep them on a plain startswith() match.
_PUBLIC_PREFIXES_LOOSE = (
    "/docs",
    "/openapi",
    "/redoc",
)
_OAUTH_PUBLIC_GET_RE = re.compile(r"^/v1/auth/oauth/(?P<provider>[^/]{1,128})/(?:start|callback)$")

_PUBLIC_EXACT = frozenset(
    {
        "/",
        "/v1/setup/status",
        "/v1/setup/presets",
        "/v1/auth/login",
        "/v1/auth/register",
        "/v1/auth/whoami",
        "/favicon.ico",
    }
)

_ADMIN_CHAT_BLOCKED = ("/v1/chat/",)

# Compatibility export for tests and callers that inspect the policy table.
# scripts/check_enumerations.py imports this alias; the single table lives in
# services/authorization.py beside the UI contract it feeds.
_PROTECTED_OPS = authorization.PROTECTED_OPS


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


def _session_id(cookies: Mapping[str, str], authorization: str | None) -> str | None:
    session_id = cookies.get("hive_session")
    if not session_id:
        auth_header = authorization or ""
        if auth_header.startswith("Bearer "):
            session_id = auth_header[7:]
    return session_id or None


def resolve_principal(
    cookies: Mapping[str, str],
    authorization: str | None,
    *,
    refresh_activity: bool = False,
) -> dict[str, Any] | None:
    session_id = _session_id(cookies, authorization)
    if not session_id:
        return None
    try:
        return auth_routes.get_current_user(session_id, refresh_activity=refresh_activity)
    except Exception:
        return None


principal_has_permission = authorization.principal_has_permission


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
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if (
            path in _PUBLIC_EXACT
            or _is_public_oauth_get(request.method, path)
            or any(_matches_public_prefix(path, p) for p in _PUBLIC_PREFIXES)
            or any(path.startswith(p) for p in _PUBLIC_PREFIXES_LOOSE)
        ):
            return await call_next(request)

        # The install wizard API is only useful before first-run provisioning,
        # when no account exists yet to authenticate with. Public pre-setup;
        # normal auth applies once setup completes (same one-shot boundary as
        # /v1/setup/complete's 409 guard).
        if _matches_public_prefix(path, "/v1/install/") and not self._setup_complete():
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        if path.startswith("/v1/"):
            # Resolve first without touching the session. A permission-denied
            # request is authenticated but is not eligible activity: refreshing
            # here would let rejected polling keep a session alive.
            user = self._get_user(request)
            if user is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                )

            principal = Principal.from_legacy_dict(user)
            request.state.principal = principal

            if principal.is_admin and self._is_chat(path):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Admin account cannot use chat. Use your daily user account."
                    },
                )

            # Persona-level feedback aggregates raw entries across all
            # workspaces using that persona. A normal workspace member may not
            # inspect other workspaces' user ids, comments, or identifiers.
            # Keep the aggregate endpoint available to operators only.
            if (
                request.method == "GET"
                and path.startswith("/v1/workspaces/persona-templates/")
                and path.endswith("/feedback")
                and not principal.is_admin
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Admin permission required for persona-wide feedback"},
                )

            required_perm = self._required_permission(request)
            if required_perm and not self._check_permission(principal, required_perm):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": f"Permission '{required_perm}' required. Elevate to proceed."
                    },
                )

            # Touch only after the request has passed the authentication and
            # middleware authorization boundary. WebSocket handshakes use the
            # same server-side decision directly in routes.ws.
            session_id = getattr(request.state, "session_id", None)
            if (
                self._is_eligible_activity(request)
                and session_id is not None
                and not auth_routes.refresh_session_activity(session_id)
            ):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                )

        return await call_next(request)

    def _setup_complete(self) -> bool:
        try:
            return bool(setup_routes._is_setup_complete())
        except Exception:
            # Fail closed: if setup state can't be read, require auth.
            return True

    def _get_user(
        self, request: Request, *, refresh_activity: bool = False
    ) -> dict[str, Any] | None:
        authorization = request.headers.get("Authorization")
        session_id = _session_id(request.cookies, authorization)
        user = resolve_principal(
            request.cookies,
            authorization,
            refresh_activity=refresh_activity,
        )
        if user is not None:
            # Keep the source explicit so a voice credential on /v1/voice/*
            # is not mistaken for an opaque session that must be touched.
            request.state.session_id = session_id
            return user
        request.state.session_id = None
        # Scoped to the voice prefix on purpose. Resolving the device
        # credential for every path would make one key a second way into the
        # whole API; here it opens the surface it was issued for and nothing
        # else, and a caller holding it still gets that account's own
        # authorization for everything downstream.
        if _matches_public_prefix(request.url.path, _VOICE_PREFIX):
            return voice_identity.principal_for(authorization)
        return None

    def _is_eligible_activity(self, request: Request) -> bool:
        """Only an authenticated API request, not a health probe, slides idle expiry.

        ``whoami`` is used by SPA startup and restoration and is deliberately
        observational. CORS preflight is bypassed before this point, while
        WebSocket handshakes opt in explicitly in ``routes.ws``.
        """
        return (
            request.method not in {"OPTIONS", "HEAD"}
            and request.url.path not in auth_routes._SESSION_ACTIVITY_EXCLUDED_PATHS
        )

    def _is_chat(self, path: str) -> bool:
        return any(path.startswith(p) for p in _ADMIN_CHAT_BLOCKED)

    def _required_permission(self, request: Request) -> str | None:
        # The single policy table and its reviewed carve-outs live in
        # services/authorization.py beside the browser contract; the
        # middleware and /v1/auth/capabilities must never drift apart (#373).
        return authorization.required_permission(request.method, request.url.path)

    def _check_permission(self, user: Principal | Mapping[str, Any], perm: str) -> bool:
        return principal_has_permission(user, perm)
