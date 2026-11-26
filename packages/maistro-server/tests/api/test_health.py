"""Tests for health endpoint.

Evidence: public health endpoints expose only probe status, not operational details.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.config.settings import SandboxSettings, Settings, get_settings
from maistro_server.api.health import (
    ProbeResult,
    _check_docker,
    _check_postgres,
    _persistence_diagnostics,
)
from maistro_server.api.health import router as health_router
from maistro_server.main import app
from maistro_server.startup import StartupPhase, set_startup_phase


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_has_no_operational_details(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert set(data) == {"status"}


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

    @pytest.mark.contract("boundary")
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


def test_persistence_diagnostics_identify_ephemeral_and_durable_stores() -> None:
    class Store:
        pass

    class PgAuditLog:
        pass

    container = type(
        "Container",
        (),
        {
            "audit_log": PgAuditLog(),
            "elevation_store": Store(),
            "session_store": Store(),
            "strike_tracker": None,
            "quota_tracker": Store(),
            "learning_store": Store(),
            "usage_log": Store(),
            "usage_log_persistence": None,
            "stores_memory_backed": False,
        },
    )()

    diagnostics = _persistence_diagnostics(container)
    assert diagnostics["audit"] == {"backend": "PgAuditLog", "durable": True}
    assert diagnostics["elevation"]["durable"] is False
    assert diagnostics["strikes"] == {"backend": "none", "durable": False}


def test_persistence_diagnostics_report_memory_backed_sqlite_as_ephemeral() -> None:
    """A pathless `sqlite://` wires the durable-twin classes over :memory:.

    Reported durable just because the class name starts with "Sqlite", health
    would contradict the container's own restart-ephemeral warning (#72).
    """
    from maistro.persistence.sqlite_learnings import SqliteLearningStore

    container = type(
        "Container",
        (),
        {
            "audit_log": None,
            "elevation_store": None,
            "session_store": None,
            "strike_tracker": None,
            "quota_tracker": None,
            "learning_store": SqliteLearningStore.__new__(SqliteLearningStore),
            "usage_log": None,
            "usage_log_persistence": None,
            "stores_memory_backed": True,
        },
    )()

    diagnostics = _persistence_diagnostics(container)
    assert diagnostics["learnings"]["backend"] == "SqliteLearningStore"
    assert diagnostics["learnings"]["durable"] is False
    assert "restart-ephemeral" in str(diagnostics["learnings"]["note"])


def test_persistence_diagnostics_report_the_write_behind_usage_log() -> None:
    """Mixed persistence is reported as what it is (#72).

    The SQLite usage log records synchronously in memory and snapshots
    durably behind a flush: neither "memory-only" nor "durable on write"
    is the truthful one-word answer, so the diagnostic names the persistence
    backend, the write-behind mode, and the durability of the twin.
    """

    class Store:
        pass

    class SqliteUsagePersistence:
        pass

    container = type(
        "Container",
        (),
        {
            "audit_log": None,
            "elevation_store": None,
            "session_store": None,
            "strike_tracker": None,
            "quota_tracker": Store(),
            "learning_store": None,
            "usage_log": Store(),
            "usage_log_persistence": SqliteUsagePersistence(),
            "stores_memory_backed": False,
        },
    )()

    usage = _persistence_diagnostics(container)["usage_log"]
    assert usage["backend"] == "Store"
    assert usage["persistence_backend"] == "SqliteUsagePersistence"
    assert usage["mode"] == "write-behind; flush_usage_log required"
    assert usage["durable"] is True


def test_persistence_diagnostics_reports_pathless_write_behind_as_ephemeral() -> None:
    """A SQLite write-behind store on ``:memory:`` still vanishes on restart."""

    class Store:
        pass

    class SqliteUsageLog:
        pass

    container = type(
        "Container",
        (),
        {
            "audit_log": None,
            "elevation_store": None,
            "session_store": None,
            "strike_tracker": None,
            "quota_tracker": Store(),
            "learning_store": None,
            "usage_log": Store(),
            "usage_log_persistence": SqliteUsageLog(),
            "stores_memory_backed": True,
        },
    )()

    usage = _persistence_diagnostics(container)["usage_log"]
    assert usage["persistence_backend"] == "SqliteUsageLog"
    assert usage["mode"] == "write-behind; flush_usage_log required"
    assert usage["durable"] is False


class TestReadinessEndpoint:
    """Evidence: /health/ready checks dependencies but discloses only status."""

    def test_readiness_all_healthy_returns_200(self, client: TestClient) -> None:
        ok = ProbeResult(status="ok")
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
        ):
            response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

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
        assert response.json() == {"status": "not_ready"}

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
        assert response.json() == {"status": "ok"}
        docker.assert_not_awaited()

    def test_readiness_circuit_open_returns_503(self, client: TestClient) -> None:
        ok = ProbeResult(status="ok")
        with (
            patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
            patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
            patch("maistro.agents.circuit_breaker.llm_circuits") as mock_bank,
        ):
            mock_bank.snapshot.return_value = [
                {
                    "name": "llm:gw=gw.internal;provider=anthropic",
                    "gateway": "gw.internal",
                    "provider": "anthropic",
                    "state": "open",
                }
            ]
            response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}

    def test_readiness_detail_names_each_unhealthy_domain_and_truncates(
        self, client: TestClient
    ) -> None:
        """The admin-scoped payload identifies WHICH failure domains are
        unhealthy (#1203), and stays bounded however many there are: eight
        are named, the overflow is summarized, and no anonymous probe sees
        any of it."""
        ok = ProbeResult(status="ok")
        rows = [
            {
                "name": f"llm:gw=gw.internal;provider=p{i}",
                "gateway": "gw.internal",
                "provider": f"p{i}",
                "state": "open",
            }
            for i in range(10)
        ]
        app.dependency_overrides[get_settings] = lambda: Settings(
            require_auth=True,
            api_keys=["ops:admin:unit-test-secret"],
        )
        try:
            with (
                patch("maistro_server.api.health._check_docker", AsyncMock(return_value=ok)),
                patch("maistro_server.api.health._check_postgres", AsyncMock(return_value=ok)),
                patch("maistro.agents.circuit_breaker.llm_circuits") as mock_bank,
            ):
                mock_bank.snapshot.return_value = rows
                response = client.get(
                    "/health/ready",
                    headers={"Authorization": "Bearer unit-test-secret"},
                )
        finally:
            app.dependency_overrides.pop(get_settings, None)
        assert response.status_code == 503
        llm = response.json()["checks"]["llm_provider"]
        assert llm["status"] == "error"
        # Each named domain carries its own state — one provider outage is
        # distinguishable from a shared-gateway one by the provider slot.
        assert "provider=p0=open" in llm["detail"]
        assert "provider=p7=open" in llm["detail"]
        # Exactly eight domains are spelled out; the rest are counted, so the
        # payload cannot grow without bound as providers are discovered.
        assert "provider=p8" not in llm["detail"]
        assert "+2 more" in llm["detail"]
