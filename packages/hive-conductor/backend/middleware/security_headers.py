"""Security headers middleware.

Adds security headers to all responses:
- Strict-Transport-Security (HSTS) — only when the request looks HTTPS
- X-Frame-Options (clickjacking protection)
- X-Content-Type-Options (MIME sniffing prevention)
- Referrer-Policy (privacy)
- Permissions-Policy (browser feature restrictions)
- Content-Security-Policy (#310)

Ported from stronghold's ``api/middleware/security_headers.py`` (and mirrors
``maistro_server.api.middleware.SecurityHeadersMiddleware``).

The header-setting stays a standalone copy: hive-conductor is an app with its
own ``backend/requirements.txt``, not a package built on maistro-core, and two
short lists of static headers drifting apart costs nothing.

**The CSP does not either.** Its *shape* is validated by
``maistro.security.content_security_policy``, which refuses a policy that has
been hollowed out; its *content* — the origins this SPA actually fetches from —
lives in ``services/csp_policy.py`` next to the front end it describes.

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
from starlette.responses import JSONResponse

from maistro.security.content_security_policy import ContentSecurityPolicy
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


def _content_security_policy() -> tuple[ContentSecurityPolicy, bool]:
    """The policy to serve, and whether to serve it report-only.

    Development is the same declaration #369 introduced rather than a new
    switch: ``ALLOW_INSECURE_TRANSPORT`` is where a deployment says it is a
    local run, and start-up already refuses to combine that with a production
    cookie posture. One flag cannot be set by accident in two places.

    Report-only is separate and deliberately independent. It is the rollout
    instrument the acceptance criteria ask for — the same policy, evaluated and
    reported but not enforced — so a deployment can watch for violations before
    switching it on. It defaults to *off*, because a report-only policy that
    nobody ever promotes is a header that protects nothing while looking like
    it does.
    """
    from config import get_settings
    from services.csp_policy import conductor_policy

    settings = get_settings()
    return (
        conductor_policy(development=settings.allow_insecure_transport),
        settings.csp_report_only,
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Add security headers to the response and enforce M0 route containment."""
        # M0 containment for #482/#313. First-run account creation belongs to
        # /v1/setup/complete, which is explicitly one-shot. The legacy register
        # route is intentionally unreachable until the M2 invitation/admin
        # registration policy lands. Keep this outside AuthMiddleware's public
        # route table so a stale or accidentally re-added exemption cannot
        # silently reopen anonymous account creation.
        if request.url.path == "/v1/auth/register":
            response: Response = JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Public registration is disabled. Use initial setup or "
                        "administrator-managed provisioning."
                    )
                },
            )
        else:
            response = await call_next(request)

        if _is_https(request):
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        policy, report_only = _content_security_policy()
        response.headers[policy.header_name(report_only=report_only)] = policy.header_value()

        return response
