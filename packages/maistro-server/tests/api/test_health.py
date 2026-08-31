"""Tests for health endpoint.

Evidence: The health endpoint is the first smoke test for the platform.
It must return status, uptime, service name, and version.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.agents.circuit_breaker import CircuitState
from maistro.config.settings import SandboxSettings, Settings, get_settings
from maistro_server.api.health import ProbeResult, _check_docker, _check_postgres
from maistro_server.api.health import router as health_router
from maistro_server.main import APP_VERSION, app
from maistro_server.startup import StartupPhase, set_startup_phase


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
        # Compare against the app's own computed version rather than a
        # hardcoded literal (E1/#294) — see tests/api/test_health.py's twin.
        assert data["version"] == APP_VERSION
        assert "uptime_seconds" in data

    def test_health_uptime_is_number(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert isinstance(data["uptime_seconds"], (int, float))


class TestLivenessEndpoint:
    """Evidence: /health/live is an unconditional liveness probe (no dependency checks)."""

    def test_liveness_returns_ok(self, client: TestClient) -> None:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestStartupEndpoint:
    """The startup probe reflects lifespan state without dependency probes."""

    @staticmethod
    def _app() -> FastAPI:
        test_app = FastAPI()
        test_app.include_router(health_router)
        return test_app

    @pytest.mark.parametrize(
        "phase",
        [StartupPhase.NOT_STARTED, StartupPhase.STARTING],
    )
    def test_incomplete_startup_returns_503(self, phase: StartupPhase) -> None:
        test_app = self._app()
        set_startup_phase(test_app, phase)

        response = TestClient(test_app).get("/health/startup")

        assert response.status_code == 503
        assert response.json() == {"status": "starting", "startup_complete": False}

    def test_complete_startup_returns_200(self) -> None:
        test_app = self._app()
        set_startup_phase(test_app, StartupPhase.COMPLETE)

        response = TestClient(test_app).get("/health/startup")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "startup_complete": True}

    def test_failed_startup_returns_sanitized_503(self) -> None:
        test_app = self._app()
        set_startup_phase(test_app, StartupPhase.FAILED)

        response = TestClient(test_app).get("/health/startup")

        assert response.status_code == 503
        assert response.json() == {"status": "failed", "startup_complete": False}
        assert set(response.json()) == {"status", "startup_complete"}

    def test_startup_does_not_run_readiness_probes(self) -> None:
        test_app = self._app()
        set_startup_phase(test_app, StartupPhase.COMPLETE)

        with (
            patch(
                "maistro_server.api.health._check_docker",
                AsyncMock(side_effect=AssertionError("must not probe Docker")),
            ),
            patch(
                "maistro_server.api.health._check_postgres",
                AsyncMock(side_effect=AssertionError("must not probe PostgreSQL")),
            ),
        ):
            response = TestClient(test_app).get("/health/startup")

        assert response.status_code == 200


class TestCheckDocker:
    """Evidence: _check_docker probes the docker daemon via subprocess."""

    async def test_docker_ok(self) -> None:
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"24.0.0\n", b""))
        proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await _check_docker()
        assert result.status == "ok"
        assert result.detail == ""
        assert result.latency_ms >= 0

    async def test_docker_nonzero_exit(self) -> None:
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b"error"))
        proc.returncode = 1
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await _check_docker()
        assert result.status == "error"
        assert result.detail == "docker info failed"

    async def test_docker_binary_not_found(self) -> None:
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError()),
        ):
            result = await _check_docker()
        assert result.status == "error"
        assert result.detail == "docker binary not found"

    async def test_docker_probe_times_out(self) -> None:
        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError())
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await _check_docker()
        assert result.status == "error"
        assert result.detail == "docker probe timed out"

    async def test_docker_unexpected_exception(self) -> None:
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            result = await _check_docker()
        assert result.status == "error"
        assert result.detail == "boom"


class TestCheckPostgres:
    """Evidence: _check_postgres probes connectivity via asyncpg."""

    async def test_postgres_ok(self) -> None:
        settings = Settings(require_auth=False)
        mock_conn = AsyncMock()
        mock_connect = AsyncMock(return_value=mock_conn)
        with patch("maistro_server.api.health.asyncpg.connect", mock_connect):
            result = await _check_postgres(settings)
        assert result.status == "ok"
        mock_conn.close.assert_awaited_once()

    async def test_postgres_connection_error(self) -> None:
        settings = Settings(require_auth=False)
        mock_connect = AsyncMock(side_effect=RuntimeError("connection refused"))
        with patch("maistro_server.api.health.asyncpg.connect", mock_connect):
            result = await _check_postgres(settings)
        assert result.status == "error"
        assert "connection refused" in result.detail

    async def test_postgres_error_detail_truncated(self) -> None:
        settings = Settings(require_auth=False)
        mock_connect = AsyncMock(side_effect=RuntimeError("x" * 500))
        with patch("maistro_server.api.health.asyncpg.connect", mock_connect):
            result = await _check_postgres(settings)
        assert result.status == "error"
        assert len(result.detail) == 100


class TestReadinessEndpoint:
    """Evidence: /health/ready aggregates docker/postgres/llm-circuit checks."""

    def test_readiness_all_healthy_returns_200(self, client: TestClient) -> None:
        ok = ProbeResult(status="ok")
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            response = client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["checks"]["docker"]["status"] == "ok"
        assert data["checks"]["postgres"]["status"] == "ok"
        assert data["checks"]["llm_provider"]["status"] == "ok"
        assert data["checks"]["llm_provider"]["detail"] == "circuit=closed"

    def test_readiness_docker_down_returns_503(self, client: TestClient) -> None:
        ok = ProbeResult(status="ok")
        bad = ProbeResult(status="error", detail="docker binary not found")
        app.dependency_overrides[get_settings] = lambda: Settings(
            require_auth=False,
            sandbox=SandboxSettings(readiness_required=True),
        )
        try:
            with (
                patch("maistro_server.api.health._check_docker", AsyncMock(return_value=bad)),
                patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
            ):
                response = client.get("/health/ready")
        finally:
            app.dependency_overrides.pop(get_settings, None)
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["docker"]["status"] == "error"

    def test_readiness_does_not_require_an_unconfigured_docker_sandbox(
        self, client: TestClient
    ) -> None:
        ok = ProbeResult(status="ok")
        docker = AsyncMock(side_effect=AssertionError("Docker should not be probed"))
        with (
            patch("maistro_server.api.health._check_docker", docker),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["checks"]["docker"]["detail"] == (
            "Docker sandbox is not required by this deployment"
        )
        docker.assert_not_awaited()

    def test_readiness_circuit_open_returns_503(self, client: TestClient) -> None:
        ok = ProbeResult(status="ok")
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
            patch("maistro.agents.circuit_breaker.llm_circuit") as mock_circuit,
        ):
            mock_circuit.state = CircuitState.OPEN
            response = client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["checks"]["llm_provider"]["status"] == "error"
        assert data["checks"]["llm_provider"]["detail"] == "circuit=open"
