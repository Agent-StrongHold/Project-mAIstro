"""Contract tests for the secured Prometheus metrics endpoint."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.auth import Scope, ServiceKeyAuthProvider, ServiceKeyRegistry
from maistro.observability.metrics import PROMETHEUS_CONTENT_TYPE, MetricsRegistry
from maistro_server.api import metrics as metrics_api

_KEY = "sk-svc-prometheus-test"


def _provider(*scopes: str) -> ServiceKeyAuthProvider:
    registry = ServiceKeyRegistry()
    registry.load_dict({"prometheus": {"key": _KEY, "scopes": list(scopes)}})
    return ServiceKeyAuthProvider(registry)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(metrics_api.router)
    return app


def test_metrics_endpoint_requires_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = MetricsRegistry()
    registry.counter("api_requests_total", "API requests").inc(method="GET")
    monkeypatch.setattr(metrics_api, "registry", registry)
    monkeypatch.setattr(metrics_api, "_metrics_auth_provider", lambda: _provider())

    response = TestClient(_app()).get("/metrics")

    assert response.status_code == 401
    assert "api_requests_total" not in response.text
    assert "uptime_seconds" not in response.text


def test_metrics_endpoint_accepts_scoped_scraper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = MetricsRegistry()
    registry.counter("api_requests_total", "API requests").inc(method="GET")
    monkeypatch.setattr(metrics_api, "registry", registry)
    monkeypatch.setattr(
        metrics_api,
        "_metrics_auth_provider",
        lambda: _provider(Scope.METRICS_READ.value),
    )

    response = TestClient(_app()).get("/metrics", headers={"X-Service-Key": _KEY})

    assert response.status_code == 200
    assert response.headers["content-type"] == PROMETHEUS_CONTENT_TYPE
    assert response.text.startswith(
        "# HELP api_requests_total API requests\n"
        "# TYPE api_requests_total counter\n"
        'api_requests_total{method="GET"} 1.0\n'
    )
    assert "# TYPE uptime_seconds gauge\n" in response.text


def test_metrics_endpoint_rejects_service_without_metrics_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        metrics_api,
        "_metrics_auth_provider",
        lambda: _provider(Scope.TRACES_READ.value),
    )

    response = TestClient(_app()).get("/metrics", headers={"X-Service-Key": _KEY})

    assert response.status_code == 403
    assert response.json() == {"detail": "Metrics scope required"}
    assert "# HELP" not in response.text


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Forwarded-For": "198.51.100.9", "X-Forwarded-Proto": "https"},
    ],
)
def test_forwarded_headers_do_not_bypass_metrics_auth(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
) -> None:
    monkeypatch.setattr(metrics_api, "_metrics_auth_provider", lambda: _provider())

    response = TestClient(_app()).get("/metrics", headers=headers)

    assert response.status_code == 401
    assert "metrics_series_overflow_total" not in response.text


def test_scoped_scraper_works_through_forwarded_proxy_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        metrics_api,
        "_metrics_auth_provider",
        lambda: _provider(Scope.METRICS_READ.value),
    )

    response = TestClient(_app()).get(
        "/metrics",
        headers={
            "X-Service-Key": _KEY,
            "X-Forwarded-For": "198.51.100.9",
            "X-Forwarded-Proto": "https",
        },
    )

    assert response.status_code == 200


def test_metrics_auth_provider_loads_scraper_from_canonical_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the real cached factory, which every other test stubs out.

    The endpoint dependency resolves its provider through the lru_cache'd
    ``_metrics_auth_provider``; patching it in the tests above proves the
    scope contract but leaves the production loader — ServiceKeyRegistry
    built from the SERVICE_KEY_*/SERVICE_SCOPES_* env contract — unexercised.
    This test runs that path end to end: env-configured scraper identity,
    scope check, and the authenticated/unauthenticated endpoint outcomes
    through the unpatched dependency.
    """
    monkeypatch.setenv("SERVICE_KEY_PROMETHEUS", _KEY)
    monkeypatch.setenv("SERVICE_SCOPES_PROMETHEUS", Scope.METRICS_READ.value)
    monkeypatch.delenv("SERVICE_KEYS_FILE", raising=False)
    metrics_api._metrics_auth_provider.cache_clear()
    try:
        provider = metrics_api._metrics_auth_provider()

        # Starlette lowercases header names, and the provider reads the
        # lowercase form — mirror the production dict(request.headers) shape.
        identity = provider.authenticate({"x-service-key": _KEY})
        assert identity is not None
        assert identity.has_scope(Scope.METRICS_READ)
        assert provider.authenticate({}) is None

        app = FastAPI()
        app.include_router(metrics_api.router)
        scoped = TestClient(app).get("/metrics", headers={"X-Service-Key": _KEY})
        assert scoped.status_code == 200
        anonymous = TestClient(app).get("/metrics")
        assert anonymous.status_code == 401
    finally:
        # Drop the real provider from the cache so no later test resolves the
        # dependency against this test's (monkeypatched-away) env state.
        metrics_api._metrics_auth_provider.cache_clear()
