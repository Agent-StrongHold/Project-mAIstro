"""Tests for health endpoint.

Evidence: The health endpoint is the first smoke test for the platform.
Public probes expose only liveness/readiness status (#365); operational
details (service identity, version, uptime) stay off the public surface.
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

    def test_health_has_no_operational_details(self, client: TestClient) -> None:
        """Minimal public liveness: no service name, version, or uptime."""
        data = client.get("/health").json()
        assert set(data) == {"status"}
        assert APP_VERSION  # the app still carries a version; it is just not public
