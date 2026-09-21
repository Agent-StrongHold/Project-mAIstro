"""Readiness diagnostics identify the configured strike tracker backend."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro.security.strikes import InMemoryStrikeTracker  # type: ignore[import-not-found]
from maistro_server.api.health import ProbeResult
from maistro_server.main import app


def _settings() -> Settings:
    return Settings()


def test_readiness_reports_disabled_strike_tracker() -> None:
    settings = _settings()
    app.dependency_overrides[get_settings] = lambda: settings
    previous = getattr(app.state, "container", None)
    app.state.container = SimpleNamespace(strike_tracker=None)
    ok = ProbeResult(status="ok")
    try:
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            response = TestClient(app).get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.state.container = previous

    assert response.status_code == 200
    assert response.json()["strike_tracker"] == {"enabled": False, "backend": "none"}


def test_readiness_reports_in_memory_strike_tracker() -> None:
    settings = _settings()
    app.dependency_overrides[get_settings] = lambda: settings
    previous = getattr(app.state, "container", None)
    app.state.container = SimpleNamespace(strike_tracker=InMemoryStrikeTracker())
    ok = ProbeResult(status="ok")
    try:
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            response = TestClient(app).get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.state.container = previous

    assert response.status_code == 200
    assert response.json()["strike_tracker"] == {
        "enabled": True,
        "backend": "InMemoryStrikeTracker",
    }
