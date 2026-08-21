"""Tests for SecurityHeadersMiddleware.

No stronghold test exists for this middleware (confirmed absent — only
PayloadSizeLimitMiddleware and DemoCookieMiddleware are covered in
stronghold's tests/api/test_middleware.py), so these are written from
scratch. Drives the full ``maistro_server.main.app`` via TestClient, since
SecurityHeadersMiddleware takes no constructor args and is wired
unconditionally — no settings override needed (see test_main.py for the
same client pattern).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from maistro_server.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestSecurityHeadersPresence:
    """Every response — success or error — carries the security headers."""

    def test_headers_present_on_success_response(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"

    def test_headers_present_on_error_response(self, client: TestClient) -> None:
        """Headers must also land on responses from inner middleware/handlers
        (e.g. a plain 404), since SecurityHeadersMiddleware wraps everything."""
        response = client.get("/tasks/does-not-exist")
        assert response.status_code == 404
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_hsts_absent_over_plain_http(self, client: TestClient) -> None:
        """TestClient issues plain-HTTP requests (scheme "http"), so HSTS —
        gated behind _is_https — must not be sent; sending it would tell
        browsers to force HTTPS for a host that isn't serving it."""
        response = client.get("/health")
        assert "Strict-Transport-Security" not in response.headers

    def test_hsts_present_when_forwarded_proto_is_https(self, client: TestClient) -> None:
        """A TLS-terminating reverse proxy signals HTTPS via
        X-Forwarded-Proto; the middleware should then send HSTS."""
        response = client.get("/health", headers={"X-Forwarded-Proto": "https"})
        assert response.headers["Strict-Transport-Security"] == (
            "max-age=63072000; includeSubDomains"
        )
