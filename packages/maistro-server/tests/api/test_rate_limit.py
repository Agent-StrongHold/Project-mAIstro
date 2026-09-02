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
