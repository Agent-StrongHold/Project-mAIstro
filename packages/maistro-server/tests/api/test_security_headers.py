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


def _proxied_client(peer: str) -> TestClient:
    """A client whose requests appear to come from `peer`.

    Constructed without a `with` block, exactly like the `client` fixture
    above: entering the context manager runs the app's lifespan, which requires
    ROUTER_API_KEY and other deployment settings this file has no business
    supplying. These tests are about response headers, not startup.

    The explicit peer is necessary because Starlette's default is the literal
    string `testclient`, which is not an IP address and so can never be a
    trusted proxy — the right default here, since it means a forwarded header
    has to be earned.
    """
    return TestClient(app, client=(peer, 45678))


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

    def test_hsts_absent_when_an_untrusted_caller_claims_https(self, client: TestClient) -> None:
        """This test used to assert the opposite, and in doing so encoded the
        defect: `X-Forwarded-Proto` was believed from whoever sent it, so any
        caller could tell a plain-HTTP deployment to answer with HSTS for two
        years including subdomains (#369).

        A TLS-terminating reverse proxy does signal HTTPS this way — but only a
        proxy the deployment named may be believed, which is the case below."""
        response = client.get("/health", headers={"X-Forwarded-Proto": "https"})
        assert "Strict-Transport-Security" not in response.headers

    def test_hsts_present_when_a_trusted_proxy_reports_https(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The legitimate arrangement: TLS terminated at a reverse proxy the
        deployment named, in front of a plain-HTTP upstream.

        Starlette's default peer is the literal string `testclient`, which is
        not an IP address and so can never be a trusted proxy — hence the
        explicit `client=` here."""
        monkeypatch.setenv("MAISTRO_TRUSTED_PROXY_IPS", "10.0.0.0/8")
        response = _proxied_client("10.1.2.3").get(
            "/health", headers={"X-Forwarded-Proto": "https"}
        )

        assert response.headers["Strict-Transport-Security"] == (
            "max-age=63072000; includeSubDomains"
        )

    def test_hsts_absent_when_a_trusted_proxy_reports_plain_http(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Trust runs both ways: a proxy that says the browser used plain HTTP
        is the authority on that."""
        monkeypatch.setenv("MAISTRO_TRUSTED_PROXY_IPS", "10.0.0.0/8")
        response = _proxied_client("10.1.2.3").get("/health", headers={"X-Forwarded-Proto": "http"})

        assert "Strict-Transport-Security" not in response.headers
