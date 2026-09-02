"""Tests for SecurityHeadersMiddleware.

The static headers are hive-conductor's own port. The HTTPS decision is
imported from ``maistro.security.transport`` — see that module and #369 for
why a decision this shape stopped being duplicated per app.

Written from scratch, following this test dir's convention of driving the real
``main:app`` + middleware stack via TestClient (see test_auth_middleware.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from main import app


def _client(peer: str | None = None) -> TestClient:
    """A client whose requests appear to come from `peer`.

    Starlette's default peer is the literal string ``testclient``, which is not
    an IP address and so is never a trusted proxy. That is the right default
    for these tests — it means a forwarded header has to be *earned* — but it
    also means testing the legitimate reverse-proxy arrangement needs a real
    address here.
    """
    if peer is None:
        return TestClient(app)
    return TestClient(app, client=(peer, 45678))


@pytest.fixture
def trust_local_proxy(monkeypatch: pytest.MonkeyPatch):
    """Name 10.0.0.0/8 as a trusted proxy, as a real deployment would."""
    from config import get_settings

    monkeypatch.setenv("TRUSTED_PROXY_IPS", "10.0.0.0/8")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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

    def test_public_registration_is_fail_closed(self) -> None:
        """A stranger cannot self-register on a provisioned hive (#313).

        M0 pinned this as an unconditional middleware 403 "while #313 is
        deferred". The M2 policy it was waiting for has landed, so the
        middleware returned to pure headers and the durable registration
        policy — enforced in the route — is the gate. This test keeps the
        containment claim honest through the full stack: conftest seeds a
        provisioned instance (the exact state the old `_registration_allowed()`
        bug read as "signup open"), and the anonymous attempt must still be
        refused, with the security headers landing on the refusal.
        """
        c = _client()
        r = c.post(
            "/v1/auth/register",
            json={
                "username": "stranger",
                "password": "securepass1",
                "confirm_password": "securepass1",
            },
        )
        assert r.status_code == 403
        assert r.json()["detail"].startswith("Registration is closed")
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"

    def test_hsts_absent_over_plain_http(self) -> None:
        """TestClient issues plain-HTTP requests, so HSTS must not be sent."""
        c = _client()
        r = c.get("/health")
        assert "Strict-Transport-Security" not in r.headers

    def test_hsts_absent_when_an_untrusted_caller_claims_https(self) -> None:
        """This test used to assert the opposite, and in doing so encoded the
        defect: any caller could send ``X-Forwarded-Proto: https`` to a
        plain-HTTP deployment and be answered with HSTS for two years including
        subdomains (#369). A header that decides a security control, believed
        from whoever sends it, is a control that is not enforced."""
        c = _client()
        r = c.get("/health", headers={"X-Forwarded-Proto": "https"})
        assert "Strict-Transport-Security" not in r.headers

    def test_hsts_present_when_a_trusted_proxy_reports_https(self, trust_local_proxy) -> None:
        """The legitimate arrangement the header exists for: TLS terminated at
        a reverse proxy the deployment named, in front of a plain-HTTP
        upstream."""
        c = _client(peer="10.1.2.3")
        r = c.get("/health", headers={"X-Forwarded-Proto": "https"})
        assert r.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains"

    def test_hsts_absent_when_a_trusted_proxy_reports_plain_http(self, trust_local_proxy) -> None:
        """Trust runs both ways: a proxy that says the browser used plain HTTP
        is the authority on that."""
        c = _client(peer="10.1.2.3")
        r = c.get("/health", headers={"X-Forwarded-Proto": "http"})
        assert "Strict-Transport-Security" not in r.headers

    def test_hsts_absent_when_a_peer_outside_the_trusted_block_claims_https(
        self, trust_local_proxy
    ) -> None:
        """Being *an* IP address is not enough — it has to be one the
        deployment named."""
        c = _client(peer="203.0.113.9")
        r = c.get("/health", headers={"X-Forwarded-Proto": "https"})
        assert "Strict-Transport-Security" not in r.headers
