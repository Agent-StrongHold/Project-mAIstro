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
