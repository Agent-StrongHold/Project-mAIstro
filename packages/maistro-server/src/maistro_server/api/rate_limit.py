"""Rate limiting middleware.

Wraps the shared `maistro.security.rate_limiter.InMemoryRateLimiter`
(sliding-window-per-key limiter) instead of an ad-hoc per-IP token bucket.

#842: the bucket identity is the **canonical authenticated principal** when
the request carries a valid credential, and a bounded **pre-auth client
identity** (the connecting client's address) otherwise — never raw
credential text. Consequences:

* rotating a secret, or holding several keys for one principal (the #843
  rotation form), stays inside that principal's one bucket;
* changing/omitting/forging an Authorization string cannot mint a fresh
  bucket — invalid credentials fall into the same pre-auth bucket as no
  credential at all;
* key material never becomes a bucket id, label, or header.

The limiter runs before the route's auth dependency, so it resolves the
bearer through the *same* canonical resolver the endpoints use
(`resolve_token_principal`); it does not re-parse or re-authenticate
credentials a second way (#842 stop condition).

**Enforcement scope (per #842 AC):** the limiter state is process-local.
Each replica enforces `rate_limit_per_minute` independently, so the
effective aggregate budget of an N-replica deployment is N x the configured
limit. It is deliberately NOT advertised as cluster-wide; sharing state
across replicas would require a coordinated store (e.g. the Redis the full
stack already runs) and is a separate change.

Proxy handling: the pre-auth identity is `request.client.host`, i.e. the
address the connection actually came from. Arbitrary `X-Forwarded-*`
headers are ignored — a forwarded address is only ever honoured when the
fronting proxy is trusted (uvicorn `--proxy-headers` +
`--forwarded-allow-ips`, which rewrite `scope["client"]` upstream of this
middleware), which is exactly the trusted-proxy policy.

Returns HTTP 429 with X-RateLimit-* and Retry-After headers when the limit
is exceeded.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Match

from maistro.config.settings import get_settings
from maistro.observability.metrics import (
    http_request_duration,
    http_requests_total,
    maistro_request_duration_seconds,
)
from maistro.security._types import RateLimitConfig
from maistro.security.rate_limiter import InMemoryRateLimiter
from maistro_server.api.auth import resolve_token_principal


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
        """Extract the rate-limit bucket key from the request (#842).

        Priority: canonical authenticated principal > pre-auth client IP.

        A valid bearer resolves — through the one canonical resolver the
        endpoints also use — to the principal's stable id, so the bucket
        survives credential rotation and multiple keys per principal.
        Anything else (no header, non-Bearer scheme, unknown/invalid token)
        falls back to the connecting client's address: a bounded identity
        that no attacker-controlled header content can rotate.

        The returned value is an internal rate-limit bucket key (never
        rendered to clients), so it is constructed via ``str.join`` rather
        than an f-string.
        """
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            principal = resolve_token_principal(token.strip(), get_settings())
            if principal is not None:
                return ":".join(("principal", principal.user_id))

        client = request.client
        ip = client.host if client else "unknown"
        return ":".join(("ip", ip))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health endpoints
        if request.url.path.startswith("/health"):
            return await call_next(request)

        key = self._extract_key(request)
        started = time.monotonic()
        allowed, headers = await self._limiter.check(key)

        if not allowed:
            retry_after = headers.get("X-RateLimit-Reset", "60")
            route = _route_template(request)
            http_requests_total.inc(method=request.method, route=route, status="429")
            # Rejections are traffic too. Omitting them understated volume and
            # latency during exactly the overload the metric exists to show.
            maistro_request_duration_seconds.observe(
                time.monotonic() - started,
                route=route,
                outcome="4xx",
            )
            return JSONResponse(
                status_code=429,
                content={"error": {"type": "rate_limited", "message": "Too many requests"}},
                headers={**headers, "Retry-After": retry_after},
            )

        await self._limiter.record(key)

        response = await call_next(request)
        duration = time.monotonic() - started
        route = _route_template(request)

        http_requests_total.inc(
            method=request.method, route=route, status=str(response.status_code)
        )
        http_request_duration.observe(duration, method=request.method, route=route)
        maistro_request_duration_seconds.observe(
            duration,
            route=route,
            outcome=f"{response.status_code // 100}xx",
        )
        return response


def _route_template(request: Request) -> str:
    """The matched route's path template (ADR-037's low-cardinality `route`
    label) — never the raw URL, which would explode the label space with ids.

    On the rate-limited path the router has not run yet, so `scope["route"]`
    is unset and every rejection would otherwise collapse into one unattributed
    bucket. Matching against the app's routes recovers the template while
    keeping the label space bounded to routes that actually exist.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str):
        return template
    return _match_route_template(request)


def _match_route_template(request: Request) -> str:
    try:
        for candidate in request.app.routes:
            match, _ = candidate.matches(request.scope)
            if match is Match.FULL:
                path = getattr(candidate, "path", None)
                if isinstance(path, str):
                    return path
    except Exception:  # never let metric labelling break a request
        return "unrouted"
    return "unrouted"
