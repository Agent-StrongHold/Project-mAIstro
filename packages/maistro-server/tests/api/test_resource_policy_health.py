"""Readiness diagnostics expose the effective resource/security policy."""

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


@pytest.mark.ac("SPEC-082226-2a10/AC-6")
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
def test_readiness_exposes_effective_container_limits(
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
    ok = ProbeResult(status="ok")
    with (
        patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
        patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
    ):
        response = TestClient(app).get("/health/ready")

    assert response.status_code == 200
    assert response.json()["container_limits"] == expected


def _cgroup_tree(root: Path) -> Path:
    root.mkdir()
    (root / "memory.max").write_text("536870912\n")
    (root / "pids.max").write_text("max\n")
    (root / "cpu.max").write_text("200000 100000\n")
    return root


@pytest.mark.parametrize(
    ("headers", "visible"),
    [
        ({}, False),
        ({"Authorization": "Bearer wrong"}, False),
        ({"Authorization": "Bearer user-secret"}, False),
        ({"Authorization": "Bearer admin-secret"}, True),
    ],
)
def test_container_limits_are_withheld_from_non_admin_callers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    headers: dict[str, str],
    visible: bool,
) -> None:
    """`/health` is a public probe prefix; deployment capacity is admin-only."""
    monkeypatch.setattr(health, "CGROUP_ROOT", _cgroup_tree(tmp_path / "cgroup"))
    settings = Settings(api_keys=["ops:admin:admin-secret", "alice:user-secret"])
    app.dependency_overrides[get_settings] = lambda: settings
    ok = ProbeResult(status="ok")
    try:
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            response = TestClient(app).get("/health/ready", headers=headers)
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    limits = response.json()["container_limits"]
    if visible:
        assert limits == {
            "memory_max_bytes": 536870912,
            "pids_max": "unbounded",
            "cpu_max_cores": 2.0,
        }
    else:
        assert limits is None
