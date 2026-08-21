"""Tests for SecurityHeadersMiddleware (hive-conductor's own port — no
dependency on maistro-server/maistro-core in backend/requirements.txt).

No stronghold test exists for this middleware — written from scratch,
following this test dir's convention of driving the real ``main:app`` +
middleware stack via TestClient (see test_auth_middleware.py).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from main import app


def _client() -> TestClient:
    return TestClient(app)


class TestSecurityHeadersPresence:
    def test_headers_present_on_success_response(self) -> None:
        c = _client()
        r = c.get("/health")
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert r.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"

    def test_headers_present_on_error_response(self) -> None:
        """Headers must also land on responses rejected by inner middleware
        (e.g. AuthMiddleware's 401), since SecurityHeadersMiddleware is the
        outermost layer and wraps everything."""
        c = _client()
        r = c.get("/v1/tasks")
        assert r.status_code == 401
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"

    def test_hsts_absent_over_plain_http(self) -> None:
        """TestClient issues plain-HTTP requests, so HSTS must not be sent."""
        c = _client()
        r = c.get("/health")
        assert "Strict-Transport-Security" not in r.headers

    def test_hsts_present_when_forwarded_proto_is_https(self) -> None:
        c = _client()
        r = c.get("/health", headers={"X-Forwarded-Proto": "https"})
        assert r.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains"
