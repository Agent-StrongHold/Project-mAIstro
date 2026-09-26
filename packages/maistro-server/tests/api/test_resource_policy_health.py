"""Readiness exposes the effective resource/security policy only to admins."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro_server.api import health
from maistro_server.api.health import ProbeResult
from maistro_server.main import app


@pytest.fixture(autouse=True)
def _pristine_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """`conftest.py` turns the unsafe override on suite-wide so its high rate
    limits are legal. This test asserts the exact diagnostic payload, including
    `unsafe_overrides_enabled: False`, so it has to construct `Settings` as an
    ordinary deployment would."""
    monkeypatch.delenv("ALLOW_UNSAFE_RESOURCE_OVERRIDES", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("RATE_LIMIT_BURST", raising=False)


def _pristine_settings() -> Settings:
    return Settings(
        max_request_body_bytes=512_000,
        max_webhook_body_bytes=256_000,
        rate_limit_per_minute=30,
        rate_limit_burst=5,
        circuit_breaker_failure_threshold=3,
        circuit_breaker_recovery_timeout_s=90,
    )


def _secured_settings() -> Settings:
    """Auth-enabled deployment with one admin and one user key (#365/#1567)."""
    return Settings(
        api_keys=["ops:admin:admin-secret", "alice:user-secret"],
        max_request_body_bytes=512_000,
        max_webhook_body_bytes=256_000,
        rate_limit_per_minute=30,
        rate_limit_burst=5,
        circuit_breaker_failure_threshold=3,
        circuit_breaker_recovery_timeout_s=90,
    )


def _probe_readiness(settings: Settings, headers: dict[str, str] | None = None) -> object:
    app.dependency_overrides[get_settings] = lambda: settings
    ok = ProbeResult(status="ok")
    try:
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            return TestClient(app).get("/health/ready", headers=headers)
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.ac("SPEC-082226-2a10/AC-6")
def test_readiness_hides_effective_resource_policy_from_anonymous_callers() -> None:
    response = _probe_readiness(_pristine_settings())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "effective_resource_policy" not in response.text


@pytest.mark.ac("SPEC-082226-2a10/AC-6")
def test_readiness_exposes_effective_resource_policy_to_admin_callers() -> None:
    response = _probe_readiness(
        _secured_settings(), headers={"Authorization": "Bearer admin-secret"}
    )

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


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (
            {"memory.max": "536870912\n", "pids.max": "max\n", "cpu.max": "200000 100000\n"},
            {"memory_max_bytes": 536870912, "pids_max": "unbounded", "cpu_max_cores": 2.0},
        ),
        (
            None,
            {"memory_max_bytes": "unknown", "pids_max": "unknown", "cpu_max_cores": "unknown"},
        ),
    ],
)
def test_readiness_exposes_effective_container_limits_to_admin_callers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    files: dict[str, str] | None,
    expected: dict[str, int | float | str],
) -> None:
    root = tmp_path / "cgroup"
    if files is not None:
        root.mkdir()
        for name, content in files.items():
            (root / name).write_text(content)
    monkeypatch.setattr(health, "CGROUP_ROOT", root)
    app.dependency_overrides[get_settings] = lambda: _secured_settings()
    ok = ProbeResult(status="ok")
    try:
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            response = TestClient(app).get(
                "/health/ready", headers={"Authorization": "Bearer admin-secret"}
            )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    assert response.json()["container_limits"] == expected


def _cgroup_tree(root: Path) -> Path:
    root.mkdir()
    (root / "memory.max").write_text("536870912\n")
    (root / "pids.max").write_text("max\n")
    (root / "cpu.max").write_text("200000 100000\n")
    return root


@pytest.mark.parametrize(
    ("headers", "detailed"),
    [
        ({}, False),
        ({"Authorization": "Bearer wrong"}, False),
        ({"Authorization": "Bearer user-secret"}, False),
        ({"Authorization": "Bearer admin-secret"}, True),
    ],
)
def test_readiness_diagnostics_are_withheld_from_non_admin_callers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    headers: dict[str, str],
    detailed: bool,
) -> None:
    """`/health` is a public probe prefix; operational configuration is
    admin-only (#365), and the whole detailed payload — not just
    `container_limits` — is withheld from everyone else (#1567)."""
    monkeypatch.setattr(health, "CGROUP_ROOT", _cgroup_tree(tmp_path / "cgroup"))
    response = _probe_readiness(_secured_settings(), headers=headers)

    assert response.status_code == 200
    body = response.json()
    if detailed:
        assert body["container_limits"] == {
            "memory_max_bytes": 536870912,
            "pids_max": "unbounded",
            "cpu_max_cores": 2.0,
        }
        assert "effective_resource_policy" in body
        assert "strike_tracker" in body
    else:
        assert body == {"status": "ok"}
        assert "container_limits" not in body
        assert "effective_resource_policy" not in body
        assert "strike_tracker" not in body


def test_auth_disabled_deployments_keep_the_minimal_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With API auth disabled no authorization decision can be made, so the
    detailed payload stays off the wire entirely (#365)."""
    monkeypatch.setattr(health, "CGROUP_ROOT", _cgroup_tree(tmp_path / "cgroup"))
    response = _probe_readiness(Settings())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
