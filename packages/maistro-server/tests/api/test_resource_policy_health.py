"""Readiness diagnostics expose the effective resource/security policy."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro_server.api.health import ProbeResult
from maistro_server.main import app


def test_readiness_exposes_effective_resource_policy() -> None:
    settings = Settings(
        max_request_body_bytes=512_000,
        max_webhook_body_bytes=256_000,
        rate_limit_per_minute=30,
        rate_limit_burst=5,
        circuit_breaker_failure_threshold=3,
        circuit_breaker_recovery_timeout_s=90,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    ok = ProbeResult(status="ok")
    try:
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            response = TestClient(app).get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    policy = response.json()["effective_resource_policy"]
    assert policy == {
        "max_request_body_bytes": 512_000,
        "max_webhook_body_bytes": 256_000,
        "rate_limit_per_minute": 30,
        "rate_limit_burst": 5,
        "circuit_breaker_failure_threshold": 3,
        "circuit_breaker_recovery_timeout_s": 90.0,
        "unsafe_overrides_enabled": False,
    }
