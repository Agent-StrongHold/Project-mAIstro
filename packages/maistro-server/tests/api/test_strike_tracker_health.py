"""Readiness diagnostics identify the configured strike tracker backend.

The backend/durability facts are operator configuration (#365/#72): they ride
the admin-gated detailed readiness payload, never the public status-only one.
"""

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
    """Auth-enabled deployment with one admin key (#365/#1567/#72)."""
    return Settings(api_keys=["ops:admin:ops-admin-secret"])


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
    # `durable` is part of the readiness contract (#72): the diagnostic must
    # say not just which backend is wired but whether it survives a restart.
    assert response.json()["strike_tracker"] == {
        "enabled": False,
        "backend": "none",
        "durable": False,
    }


def test_readiness_reports_in_memory_strike_tracker() -> None:
    response = _probe_readiness_with(
        SimpleNamespace(strike_tracker=InMemoryStrikeTracker(), stores_memory_backed=False)
    )

    assert response.status_code == 200
    assert response.json()["strike_tracker"] == {
        "enabled": True,
        "backend": "InMemoryStrikeTracker",
        "durable": False,
    }


def test_readiness_reports_postgres_strike_tracker_as_durable() -> None:
    """The durable half of the same contract (#72, #134).

    A `PgStrikeTracker` wired beside the canonical pool must read as durable —
    its lockouts survive restart, and that is the fact an operator diffing a
    readiness probe across deployments is asking about. Constructed without a
    server: the diagnostic inspects the wired tracker, it does not use it.
    """
    from maistro.security.pg_strikes import PgStrikeTracker

    response = _probe_readiness_with(
        SimpleNamespace(strike_tracker=PgStrikeTracker(pool=object()), stores_memory_backed=False)
    )

    assert response.status_code == 200
    assert response.json()["strike_tracker"] == {
        "enabled": True,
        "backend": "PgStrikeTracker",
        "durable": True,
    }


def test_readiness_hides_strike_diagnostics_from_anonymous_probes() -> None:
    """The durability facts are operational configuration, not public surface.

    An anonymous probe against the same deployment gets the status-only
    contract (#365): no backend name, no durability claim — an attacker must
    not learn whether strikes survive a restart from an unauthenticated probe.
    """
    settings = _secured_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    previous = getattr(app.state, "container", None)
    app.state.container = SimpleNamespace(
        strike_tracker=InMemoryStrikeTracker(), stores_memory_backed=False
    )
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
    assert response.json() == {"status": "ok"}
    assert "strike_tracker" not in response.text
    assert "persistence" not in response.text
