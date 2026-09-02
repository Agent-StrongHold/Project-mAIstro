"""Contract tests for the Prometheus metrics endpoint."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.observability.metrics import PROMETHEUS_CONTENT_TYPE, MetricsRegistry
from maistro_server.api import metrics as metrics_api


def test_metrics_endpoint_returns_prometheus_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = MetricsRegistry()
    registry.counter("api_requests_total", "API requests").inc(method="GET")
    monkeypatch.setattr(metrics_api, "registry", registry)
    app = FastAPI()
    app.include_router(metrics_api.router)

    response = TestClient(app).get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"] == PROMETHEUS_CONTENT_TYPE
    assert response.text.startswith(
        "# HELP api_requests_total API requests\n"
        "# TYPE api_requests_total counter\n"
        'api_requests_total{method="GET"} 1.0\n'
    )
    assert "# TYPE uptime_seconds gauge\n" in response.text
