"""Integration tests for maistro_server.api.rate_limit.RateLimitMiddleware.

The middleware is rewired (B4) to wrap the shared
`maistro.security.rate_limiter.InMemoryRateLimiter` sliding-window limiter
instead of an ad-hoc per-IP token bucket. `InMemoryRateLimiter`'s own unit
tests (packages/maistro-core/tests/security/test_rate_limiter.py) already
cover the sliding-window logic in isolation; these tests exercise the
middleware end-to-end: header presence, 429 body shape, and key-extraction
priority (Authorization header vs. client-IP fallback).

Uses a standalone FastAPI app (not the shared `maistro_server.main.app`
singleton) so each test can set its own tight rate limit via env vars —
following the `_make_app` pattern in tests/api/test_auth.py.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.config.settings import get_settings
from maistro_server.api.rate_limit import RateLimitMiddleware


def _make_app() -> FastAPI:
    """Build a minimal app with only the rate limit middleware + test routes."""
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/thing")
    def thing() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(RateLimitMiddleware)
    return app


@pytest.fixture()
def tight_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a tight rate limit so a handful of requests trips it."""
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_BURST", "0")
    get_settings.cache_clear()


class TestHealthExemption:
    def test_health_path_never_rate_limited(self, tight_limits: None) -> None:
        client = TestClient(_make_app())
        for _ in range(10):
            response = client.get("/health")
            assert response.status_code == 200


class TestRateLimitHeadersAnd429Body:
    def test_allows_requests_under_limit(self, tight_limits: None) -> None:
        client = TestClient(_make_app())
        response = client.get("/thing")
        assert response.status_code == 200

    def test_429_after_limit_exceeded(self, tight_limits: None) -> None:
        client = TestClient(_make_app())
        last_response = None
        for _ in range(5):
            last_response = client.get("/thing")
            if last_response.status_code == 429:
                break
        assert last_response is not None
        assert last_response.status_code == 429

    def test_429_response_has_rate_limit_and_retry_after_headers(self, tight_limits: None) -> None:
        client = TestClient(_make_app())
        last_response = None
        for _ in range(5):
            last_response = client.get("/thing")
            if last_response.status_code == 429:
                break
        assert last_response is not None
        assert last_response.status_code == 429
        assert "X-RateLimit-Limit" in last_response.headers
        assert "X-RateLimit-Remaining" in last_response.headers
        assert "X-RateLimit-Reset" in last_response.headers
        assert "Retry-After" in last_response.headers

    def test_429_body_shape(self, tight_limits: None) -> None:
        client = TestClient(_make_app())
        last_response = None
        for _ in range(5):
            last_response = client.get("/thing")
            if last_response.status_code == 429:
                break
        assert last_response is not None
        body = last_response.json()
        assert body["error"]["type"] == "rate_limited"
        assert body["error"]["message"] == "Too many requests"


class TestKeyExtractionPriority:
    def test_authorization_header_used_as_key_when_present(self, tight_limits: None) -> None:
        """Two different IPs (simulated by different client fixtures aren't
        available via TestClient) sharing the same Authorization header
        should share the same rate-limit bucket — i.e. the header, not the
        IP, determines the key when present."""
        client = TestClient(_make_app())
        headers = {"Authorization": "Bearer same-token"}

        first = client.get("/thing", headers=headers)
        assert first.status_code == 200
        second = client.get("/thing", headers=headers)
        assert second.status_code == 200
        # Limit is 2/minute with burst=0 — the third call against the same
        # Authorization-derived key must be denied.
        third = client.get("/thing", headers=headers)
        assert third.status_code == 429

    def test_falls_back_to_client_ip_when_no_authorization_header(self, tight_limits: None) -> None:
        client = TestClient(_make_app())
        first = client.get("/thing")
        assert first.status_code == 200
        second = client.get("/thing")
        assert second.status_code == 200
        third = client.get("/thing")
        assert third.status_code == 429

    def test_different_authorization_headers_get_independent_buckets(
        self, tight_limits: None
    ) -> None:
        client = TestClient(_make_app())
        headers_a = {"Authorization": "Bearer token-a"}
        headers_b = {"Authorization": "Bearer token-b"}

        # Exhaust token-a's bucket.
        client.get("/thing", headers=headers_a)
        client.get("/thing", headers=headers_a)
        exhausted = client.get("/thing", headers=headers_a)
        assert exhausted.status_code == 429

        # token-b has its own, still-fresh bucket.
        response_b = client.get("/thing", headers=headers_b)
        assert response_b.status_code == 200
