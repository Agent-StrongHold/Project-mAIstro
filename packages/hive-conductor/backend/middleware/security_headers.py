"""Security headers middleware.

Adds security headers to all responses:
- Strict-Transport-Security (HSTS) — only when the request looks HTTPS
- X-Frame-Options (clickjacking protection)
- X-Content-Type-Options (MIME sniffing prevention)
- Referrer-Policy (privacy)
- Permissions-Policy (browser feature restrictions)

Ported from stronghold's ``api/middleware/security_headers.py`` (and mirrors
``maistro_server.api.middleware.SecurityHeadersMiddleware``). hive-conductor
has no dependency on maistro-server or maistro-core in its
``requirements.txt`` (it's an app with its own ``backend/requirements.txt``,
not a package built on top of maistro-core), so this is a standalone copy
rather than a cross-import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response


def _is_https(request: Request) -> bool:
    """True if the request appears to have arrived over HTTPS.

    Checks the ASGI-reported scheme first, then falls back to the
    conventional ``X-Forwarded-Proto`` header set by a reverse proxy/load
    balancer terminating TLS in front of a plain-HTTP upstream. Keeps local
    dev (``uvicorn main:app --reload``, plain HTTP) from getting an HSTS
    header that would force browsers to upgrade every future request.
    """
    if request.url.scheme == "https":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return forwarded_proto.split(",")[0].strip().lower() == "https"


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
