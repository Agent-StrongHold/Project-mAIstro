"""Rate limiting middleware.

Wraps the shared `maistro.security.rate_limiter.InMemoryRateLimiter`
(sliding-window-per-key limiter) instead of an ad-hoc per-IP token bucket.
Extracts a rate-limit key from the request (Authorization header, hashed —
or client IP as a fallback) and enforces per-key request limits. Returns
HTTP 429 with X-RateLimit-* and Retry-After headers when the limit is
exceeded.
"""

from __future__ import annotations

import hashlib
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from maistro.config.settings import get_settings
from maistro.observability.metrics import http_request_duration, http_requests_total
from maistro.security._types import RateLimitConfig
from maistro.security.rate_limiter import InMemoryRateLimiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client rate limiting via the shared sliding-window limiter."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        settings = get_settings()
        self._limiter = InMemoryRateLimiter(
            RateLimitConfig(
                requests_per_minute=settings.rate_limit_per_minute,
                burst_limit=settings.rate_limit_burst,
            )
        )

    @staticmethod
    def _extract_key(request: Request) -> str:
        """Extract rate limit key from request.

        Priority: Authorization header hash > client IP.

        The returned value is an internal rate-limit bucket key (never
        rendered to clients), so it is constructed via ``str.join`` rather
        than an f-string.
        """
        auth = request.headers.get("authorization", "")
        if auth:
            digest = hashlib.sha256(auth.encode()).hexdigest()[:16]
            return ":".join(("auth", digest))

        client = request.client
        ip = client.host if client else "unknown"
        return ":".join(("ip", ip))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health endpoints
        if request.url.path.startswith("/health"):
            return await call_next(request)

        key = self._extract_key(request)
        allowed, headers = await self._limiter.check(key)

        if not allowed:
            retry_after = headers.get("X-RateLimit-Reset", "60")
            http_requests_total.inc(method=request.method, path=request.url.path, status="429")
            return JSONResponse(
                status_code=429,
                content={"error": {"type": "rate_limited", "message": "Too many requests"}},
                headers={**headers, "Retry-After": retry_after},
            )

        await self._limiter.record(key)

        t0 = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - t0

        http_requests_total.inc(
            method=request.method, path=request.url.path, status=str(response.status_code)
        )
        http_request_duration.observe(duration, method=request.method, path=request.url.path)
        return response
