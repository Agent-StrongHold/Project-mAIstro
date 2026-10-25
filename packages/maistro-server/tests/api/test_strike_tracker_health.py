"""Anonymous readiness does not identify the configured strike tracker backend."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro.security.strikes import InMemoryStrikeTracker  # type: ignore[import-not-found]
from maistro_server.api.health import ProbeResult
from maistro_server.main import app

_ADMIN_HEADERS = {"Authorization": "Bearer ops-admin-secret"}


def _secured_settings() -> Settings:
    """Auth-enabled deployment with one admin key (#365/#1567/#72).

    Authority is explicit configuration (#1095): the admin credential lives
    in ADMIN_API_KEYS, not in a ``:admin:`` secret segment. The user list
    stays non-empty because the detailed-readiness gate serves diagnostics
    only for auth-enabled deployments.
    """
    return Settings(
        api_keys=["ops:admin:ops-admin-secret"],
        admin_api_keys=["ops:ops-admin-secret"],
    )


def _probe_readiness_with(container: object) -> object:
    settings = _secured_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    previous = getattr(app.state, "container", None)
    app.state.container = container
    ok = ProbeResult(status="ok")
    try:
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            return TestClient(app).get("/health/ready", headers=_ADMIN_HEADERS)
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.state.container = previous


def test_readiness_reports_disabled_strike_tracker() -> None:
    response = _probe_readiness_with(
        SimpleNamespace(strike_tracker=None, stores_memory_backed=False)
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "strike_tracker" not in response.text


def test_readiness_reports_in_memory_strike_tracker() -> None:
    response = _probe_readiness_with(
        SimpleNamespace(strike_tracker=InMemoryStrikeTracker(), stores_memory_backed=False)
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "InMemoryStrikeTracker" not in response.text
