"""Integration tests for maistro_server.api.rate_limit.RateLimitMiddleware.

The middleware wraps the shared
`maistro.security.rate_limiter.InMemoryRateLimiter` sliding-window limiter.
`InMemoryRateLimiter`'s own unit tests
(packages/maistro-core/tests/security/test_rate_limiter.py) already cover the
sliding-window logic in isolation; these tests exercise the middleware
end-to-end: header presence, 429 body shape, and — per #842 — the identity
model of the bucket key: canonical authenticated principal when the bearer
resolves, and a bounded pre-auth client identity (the connecting IP, not
header text) otherwise.

Uses a standalone FastAPI app (not the shared `maistro_server.main.app`
singleton) so each test can set its own tight rate limit and API keys via
env vars — following the `_make_app` pattern in tests/api/test_auth.py.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.config.settings import get_settings
from maistro.observability.metrics import (
    http_request_duration,
    http_requests_total,
    maistro_request_duration_seconds,
)
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


def configure_api_keys(monkeypatch: pytest.MonkeyPatch, *entries: str) -> None:
    """Point settings at an explicit API_KEYS list (JSON, like the env var).

        The middleware resolves bearers through the canonical resolver, so these
    tests must pin the key list rather than depend on whatever the ambient
    environment carries.
    """
    monkeypatch.setenv("API_KEYS", json.dumps(list(entries)))
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
    def test_valid_credential_keys_the_principal_bucket(self, tight_limits: None) -> None:
        """A valid bearer keys the bucket on the resolved principal: the
        same token keeps hitting the same bucket until it trips."""
        client = TestClient(_make_app())
        headers = {"Authorization": "Bearer rl-key"}

        first = client.get("/thing", headers=headers)
        assert first.status_code == 200
        second = client.get("/thing", headers=headers)
        assert second.status_code == 200
        # Limit is 2/minute with burst=0 — the third call against the same
        # principal bucket must be denied.
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

    def test_different_principals_get_independent_buckets(
        self, tight_limits: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per-principal limits are real limits: exhausting one principal's
        bucket does not touch a different principal's (#842 AC: quota follows
        the canonical identity)."""
        configure_api_keys(monkeypatch, "ops:rl-secret-a", "dev:rl-secret-b")
        client = TestClient(_make_app())
        headers_ops = {"Authorization": "Bearer rl-secret-a"}
        headers_dev = {"Authorization": "Bearer rl-secret-b"}

        # Exhaust ops' bucket.
        client.get("/thing", headers=headers_ops)
        client.get("/thing", headers=headers_ops)
        exhausted = client.get("/thing", headers=headers_ops)
        assert exhausted.status_code == 429

        # dev has its own, still-fresh principal bucket.
        response_dev = client.get("/thing", headers=headers_dev)
        assert response_dev.status_code == 200


class TestPrincipalIdentityKeying:
    """#842: rate limits key to the authenticated principal, not to
    attacker-controlled bearer text."""

    def test_one_principal_many_bearer_strings_shares_one_bucket(
        self, tight_limits: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC: one principal with many bearer strings stays in one principal
        bucket — rotating credentials (or overlapping old/new keys during
        rotation) preserves the principal-level abuse history."""
        configure_api_keys(monkeypatch, "ops:rl-key-one", "ops:rl-key-two")
        client = TestClient(_make_app())

        assert (
            client.get("/thing", headers={"Authorization": "Bearer rl-key-one"}).status_code == 200
        )
        assert (
            client.get("/thing", headers={"Authorization": "Bearer rl-key-two"}).status_code == 200
        )
        # Same principal (ops), third request — regardless of which of the
        # principal's two valid secrets is presented.
        assert (
            client.get("/thing", headers={"Authorization": "Bearer rl-key-one"}).status_code == 429
        )

    def test_invalid_bearer_strings_do_not_mint_independent_buckets(
        self, tight_limits: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC: invalid bearer tokens never mint independent buckets. Every
        unrecognized credential falls into the same pre-auth client bucket
        as an unauthenticated request."""
        configure_api_keys(monkeypatch, "ops:rl-legit-key")
        client = TestClient(_make_app())

        assert (
            client.get("/thing", headers={"Authorization": "Bearer garbage-one"}).status_code == 200
        )
        assert (
            client.get("/thing", headers={"Authorization": "Bearer garbage-two"}).status_code == 200
        )
        # A third distinct bearer string — still the same pre-auth bucket.
        assert (
            client.get("/thing", headers={"Authorization": "Bearer garbage-three"}).status_code
            == 429
        )

    def test_anonymous_traffic_cannot_evade_the_network_floor_by_changing_headers(
        self, tight_limits: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC: anonymous traffic cannot evade the global/network floor by
        changing headers — mixing absent, invalid, and non-Bearer schemes
        stays inside the one pre-auth bucket."""
        configure_api_keys(monkeypatch, "ops:rl-legit-key")
        client = TestClient(_make_app())

        assert client.get("/thing").status_code == 200
        assert (
            client.get("/thing", headers={"Authorization": "Bearer not-a-key"}).status_code == 200
        )
        # Different scheme entirely — still the same connecting client.
        assert (
            client.get("/thing", headers={"Authorization": "Basic dXNlcjpwYXNz"}).status_code == 429
        )

    def test_forwarded_for_cannot_rotate_the_preauth_bucket(
        self, tight_limits: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC: proxy/client-IP handling follows the trusted-proxy policy.
        The pre-auth identity is the address the connection came from;
        arbitrary X-Forwarded-For header text must not rotate it."""
        configure_api_keys(monkeypatch, "ops:rl-legit-key")
        client = TestClient(_make_app())

        assert client.get("/thing", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 200
        assert client.get("/thing", headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 200
        assert client.get("/thing", headers={"X-Forwarded-For": "203.0.113.3"}).status_code == 429

    def test_metrics_and_responses_never_expose_credential_material(
        self, tight_limits: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC (#842, via #818's bounded labels): no metric label and no
        response surface ever carries credential material — the bucket key
        is the principal id, never the secret."""
        configure_api_keys(monkeypatch, "ops:rl-metric-secret", "dev:rl-other-secret")
        client = TestClient(_make_app())

        responses = [
            client.get("/thing", headers={"Authorization": "Bearer rl-metric-secret"}),
            client.get("/thing", headers={"Authorization": "Bearer rl-other-secret"}),
            client.get("/thing", headers={"Authorization": "Bearer rl-metric-secret"}),
            client.get("/thing", headers={"Authorization": "Bearer rl-metric-secret"}),
            client.get("/thing", headers={"Authorization": "Bearer invalid-secret"}),
        ]
        assert any(r.status_code == 429 for r in responses)

        for response in responses:
            assert "rl-metric-secret" not in response.text
            assert "rl-other-secret" not in response.text
            for header_value in response.headers.values():
                assert "rl-metric-secret" not in header_value

        metrics = (
            http_requests_total.collect()
            + http_request_duration.collect()
            + maistro_request_duration_seconds.collect()
        )
        for sample in metrics:
            for label_value in sample["labels"].values():
                assert "rl-metric-secret" not in label_value
                assert "rl-other-secret" not in label_value


class TestAdr037RequestDuration:
    def test_request_observes_route_template_and_outcome(self) -> None:
        """ADR-037's maistro_request_duration_seconds records the matched route
        TEMPLATE (low-cardinality), never the raw URL with embedded ids."""
        app = FastAPI()

        @app.get("/items/{item_id}")
        def item(item_id: str) -> dict[str, str]:
            return {"id": item_id}

        app.add_middleware(RateLimitMiddleware)
        client = TestClient(app)
        assert client.get("/items/abc123").status_code == 200

        samples = {
            (s["labels"]["route"], s["labels"]["outcome"]): s
            for s in maistro_request_duration_seconds.collect()
        }
        assert ("/items/{item_id}", "2xx") in samples
        assert not any(route == "/items/abc123" for route, _ in samples)

    def test_unrouted_request_uses_fallback_label(self) -> None:
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)
        client = TestClient(app)
        assert client.get("/no-such-route").status_code == 404

        samples = {
            (s["labels"]["route"], s["labels"]["outcome"])
            for s in maistro_request_duration_seconds.collect()
        }
        assert ("unrouted", "4xx") in samples

    def test_rate_limited_requests_are_observed_too(self, tight_limits: None) -> None:
        """Rejections are traffic. Omitting 429s understated volume and latency
        during exactly the overload the metric exists to show."""

        def counted() -> int:
            return sum(
                s["count"]
                for s in maistro_request_duration_seconds.collect()
                if s["labels"] == {"route": "/thing", "outcome": "4xx"}
            )

        before = counted()
        client = TestClient(_make_app())
        statuses = [client.get("/thing").status_code for _ in range(4)]
        assert 429 in statuses
        assert counted() >= before + statuses.count(429)


class TestBoundedRouteLabels:
    def test_legacy_request_metrics_use_route_templates(self) -> None:
        app = FastAPI()

        @app.get("/items/{item_id}")
        def item(item_id: str) -> dict[str, str]:
            return {"id": item_id}

        app.add_middleware(RateLimitMiddleware)
        client = TestClient(app)
        for item_id in ("first", "second", "third"):
            assert client.get(f"/items/{item_id}").status_code == 200

        counter_samples = [
            sample
            for sample in http_requests_total.collect()
            if sample["labels"].get("route") == "/items/{item_id}"
        ]
        histogram_samples = [
            sample
            for sample in http_request_duration.collect()
            if sample["labels"].get("route") == "/items/{item_id}"
        ]

        assert len(counter_samples) == 1
        assert counter_samples[0]["value"] >= 3
        assert len(histogram_samples) == 1
        assert histogram_samples[0]["count"] >= 3
        assert all("path" not in sample["labels"] for sample in counter_samples)
        assert all("path" not in sample["labels"] for sample in histogram_samples)

    def test_many_unknown_paths_collapse_to_one_fallback_series(self) -> None:
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)
        client = TestClient(app)
        counter_series_before = len(http_requests_total.collect())
        histogram_series_before = len(http_request_duration.collect())

        for index in range(25):
            assert client.get(f"/attacker-controlled/{index}/random").status_code == 404

        counter_samples = http_requests_total.collect()
        histogram_samples = http_request_duration.collect()
        assert len(counter_samples) <= counter_series_before + 1
        assert len(histogram_samples) <= histogram_series_before + 1
        assert any(
            sample["labels"] == {"method": "GET", "route": "unrouted", "status": "404"}
            for sample in counter_samples
        )
        assert any(
            sample["labels"] == {"method": "GET", "route": "unrouted"}
            for sample in histogram_samples
        )

    def test_many_distinct_404_uuid_paths_create_no_series_per_url(self) -> None:
        """#818 AC-2, verbatim: the middleware runs before routing/auth, so
        arbitrary 404 UUID paths are exactly the traffic that must not mint
        one metric series per URL — across every middleware-emitted metric."""
        app = FastAPI()

        @app.get("/items/{item_id}")
        def item(item_id: str) -> dict[str, str]:
            return {"id": item_id}

        app.add_middleware(RateLimitMiddleware)
        client = TestClient(app)
        series_before = {
            "counter": len(http_requests_total.collect()),
            "duration": len(http_request_duration.collect()),
            "maistro": len(maistro_request_duration_seconds.collect()),
        }

        paths = [f"/{uuid4()}" for _ in range(60)]
        paths += [f"/items/{uuid4()}" for _ in range(30)]
        for path in paths:
            assert client.get(path).status_code in (200, 404)

        # 60 distinct unmatched URLs + 30 distinct item ids collapse into at
        # most two new series per metric: the `unrouted` fallback class and
        # the `/items/{item_id}` template.
        assert len(http_requests_total.collect()) <= series_before["counter"] + 2
        assert len(http_request_duration.collect()) <= series_before["duration"] + 2
        assert len(maistro_request_duration_seconds.collect()) <= series_before["maistro"] + 2
        assert any(
            sample["labels"] == {"method": "GET", "route": "unrouted", "status": "404"}
            for sample in http_requests_total.collect()
        )
        assert any(
            sample["labels"] == {"method": "GET", "route": "/items/{item_id}", "status": "200"}
            for sample in http_requests_total.collect()
        )

    def test_distinct_routes_stay_distinguishable_without_raw_identifiers(self) -> None:
        """#818 AC-4: bounding must not flatten legitimate route-level
        observability — two real routes stay two series, and no label value
        carries a request-controlled identifier."""
        app = FastAPI()

        @app.get("/items/{item_id}")
        def item(item_id: str) -> dict[str, str]:
            return {"id": item_id}

        @app.get("/users/{user_id}/orders/{order_id}")
        def order(user_id: str, order_id: str) -> dict[str, str]:
            return {"user": user_id, "order": order_id}

        app.add_middleware(RateLimitMiddleware)
        client = TestClient(app)
        for index in range(3):
            assert client.get(f"/items/item-{index}").status_code == 200
            assert client.get(f"/users/user-{index}/orders/order-{index}").status_code == 200

        counter_by_route = {
            sample["labels"]["route"]: sample["value"]
            for sample in http_requests_total.collect()
            if sample["labels"].get("method") == "GET" and sample["labels"].get("status") == "200"
        }
        assert counter_by_route.get("/items/{item_id}", 0) >= 3
        assert counter_by_route.get("/users/{user_id}/orders/{order_id}", 0) >= 3

        for sample in http_requests_total.collect():
            route = sample["labels"].get("route", "")
            assert "item-" not in route and "user-" not in route

        histogram_routes = {
            sample["labels"]["route"] for sample in maistro_request_duration_seconds.collect()
        }
        assert {"/items/{item_id}", "/users/{user_id}/orders/{order_id}"} <= histogram_routes
