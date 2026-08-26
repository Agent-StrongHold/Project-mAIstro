"""Security headers middleware.

Adds security headers to all responses:
- Strict-Transport-Security (HSTS) — only when the request looks HTTPS
- X-Frame-Options (clickjacking protection)
- X-Content-Type-Options (MIME sniffing prevention)
- Referrer-Policy (privacy)
- Permissions-Policy (browser feature restrictions)

Ported from stronghold's ``api/middleware/security_headers.py`` (and mirrors
``maistro_server.api.middleware.SecurityHeadersMiddleware``).

The header-setting stays a standalone copy: hive-conductor is an app with its
own ``backend/requirements.txt``, not a package built on maistro-core, and two
short lists of static headers drifting apart costs nothing.

**The HTTPS decision does not**, and is imported from
``maistro.security.transport`` instead (#369). Both copies of it were wrong in
the same way — they believed ``X-Forwarded-Proto`` from any caller — and a
security decision duplicated per app is a decision that gets fixed in one place
and stays broken in the other. maistro-core is already consumed here via
``sys.path`` (``services/themes.py``, ``services/agent_materialization.py`` and
others import ``maistro.*``), so this is the established arrangement rather
than a new dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from maistro.security.transport import parse_trusted_proxies, request_is_https

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response


def _is_https(request: Request) -> bool:
    """True if the request really arrived over HTTPS.

    The ASGI-reported scheme is fact. ``X-Forwarded-Proto`` is a *claim*, and
    this used to believe it from anyone — so any caller could send
    ``X-Forwarded-Proto: https`` to a plain-HTTP deployment and be told the
    origin is HSTS-eligible for two years including subdomains (#369). It is
    now read only from a peer named in ``TRUSTED_PROXY_IPS``; nothing named
    means nothing trusted.

    Keeping local dev (``uvicorn main:app --reload``, plain HTTP) from getting
    an HSTS header that would force browsers to upgrade every future request is
    still what the gate is for.
    """
    from config import get_settings

    return request_is_https(
        scheme=request.url.scheme,
        headers=request.headers,
        client_host=request.client.host if request.client else None,
        trusted_proxies=parse_trusted_proxies(get_settings().trusted_proxy_ips),
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Add security headers to the response."""
        response: Response = await call_next(request)

        if _is_https(request):
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response
