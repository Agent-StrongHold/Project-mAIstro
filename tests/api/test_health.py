"""Tests for health endpoint.

Evidence: The health endpoint is the first smoke test for the platform.
It must return status, uptime, service name, and version.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from maistro_server.main import APP_VERSION, app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "maistro-engine"
        # Compare against the app's own computed version rather than a hardcoded
        # literal (E1/#294): dev runs often resolve `maistro_server` from
        # `PYTHONPATH` without a dist-info (APP_VERSION falls back to "X.Y.Z-dev"),
        # production images expose `importlib.metadata.version("maistro-server")`.
        assert data["version"] == APP_VERSION
        assert "uptime_seconds" in data

    def test_health_uptime_is_number(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert isinstance(data["uptime_seconds"], (int, float))
