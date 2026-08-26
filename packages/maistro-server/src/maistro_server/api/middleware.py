"""Global HTTP middleware: payload size limits and security headers.

Ported from stronghold's ``api/middleware/__init__.py`` (payload-size limit)
and ``api/middleware/security_headers.py`` (security headers), adapted to
the engine's ``ErrorResponse``/``ErrorDetail`` envelope shape and made
HTTPS-aware for HSTS (see ``_is_https``).
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from maistro.security.transport import parse_trusted_proxies, request_is_https

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request


def _request_id(request: Request) -> str:
    """Best-effort request id for error envelopes built by outermost middleware.

    Both middlewares here are wired as the outermost layer (added last), so
    they dispatch before ``RequestIDMiddleware`` has a chance to assign
    ``request.state.request_id``. Fall back to a fresh id, mirroring
    ``maistro_server.main``'s own exception-handler fallback.
    """
    return getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]


class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds the configured byte limit.

    - 413 Payload Too Large when ``Content-Length`` is negative or exceeds
      ``max_bytes``.
    - 400 Bad Request when ``Content-Length`` is present but not a valid
      integer.
    - For chunked-transfer POST/PUT/PATCH requests with no ``Content-Length``,
      the body is read and measured directly against ``max_bytes``.

    Uses the same ``ErrorResponse``/``ErrorDetail`` envelope shape as
    ``maistro_server.main``'s exception handlers (``error.type``,
    ``error.message``, ``error.request_id``) so clients see one consistent
    error format regardless of which layer rejected the request — this
    includes matching the exact "Invalid Content-Length header" message
    already used by the webhook routes' own body-size check
    (``maistro_server.api.webhooks._check_body_size``), so this global
    middleware is a superset, not a behavior change, for those routes.
    """

    def __init__(self, app: Any, max_bytes: int = 1_048_576) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    def _too_large_response(self, request: Request) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "type": "payload_error",
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": f"Payload too large (max {self._max_bytes} bytes)",
                    "request_id": _request_id(request),
                }
            },
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[..., Any],
    ) -> Response:
        content_length = request.headers.get("content-length")
        transfer_encoding = request.headers.get("transfer-encoding", "")

        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "type": "request_error",
                            "message": "Invalid Content-Length header",
                            "request_id": _request_id(request),
                        }
                    },
                )
            if length < 0 or length > self._max_bytes:
                return self._too_large_response(request)
        elif "chunked" in transfer_encoding.lower() and request.method in ("POST", "PUT", "PATCH"):
            # Chunked requests without Content-Length: read body with limit.
            body = await request.body()
            if len(body) > self._max_bytes:
                return self._too_large_response(request)

        result: Response = await call_next(request)
        return result


def _is_https(request: Request) -> bool:
    """True if the request really arrived over HTTPS.

    The ASGI-reported scheme is fact — it is true when TLS is terminated by the
    app server itself. ``X-Forwarded-Proto`` is a *claim* by whoever sent the
    request, and this used to believe it from anyone: any caller could send
    ``X-Forwarded-Proto: https`` to a plain-HTTP deployment and be answered with
    HSTS for two years including subdomains (#369).

    It is now read only from a peer the deployment named in
    ``MAISTRO_TRUSTED_PROXY_IPS``. Nothing named means nothing trusted, which
    fails in the safe direction: a deployment that forgets to configure its
    proxy loses HSTS rather than gaining a header anyone can forge.

    Keeping local dev over plain HTTP from getting an HSTS header that would
    force browsers to upgrade every future request is still the point of the
    gate.
    """
    return request_is_https(
        scheme=request.url.scheme,
        headers=request.headers,
        client_host=request.client.host if request.client else None,
        trusted_proxies=parse_trusted_proxies(os.environ.get("MAISTRO_TRUSTED_PROXY_IPS", "")),
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response.

    Sets ``X-Frame-Options``, ``X-Content-Type-Options``, ``Referrer-Policy``,
    and ``Permissions-Policy`` unconditionally. ``Strict-Transport-Security``
    (HSTS) is gated behind ``_is_https`` — stronghold's original port sends
    HSTS unconditionally, which is safe behind its always-TLS deployment
    target but would be wrong advice to a browser talking to a local plain
    HTTP dev server.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[..., Any],
    ) -> Response:
        response: Response = await call_next(request)

        if _is_https(request):
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response
