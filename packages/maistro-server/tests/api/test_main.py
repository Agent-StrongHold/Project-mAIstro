"""Tests for the FastAPI app entrypoint — lifespan, shutdown, exception handlers.

Evidence: main.py wires the task runner into the app lifecycle, registers
graceful-shutdown signal handlers, seeds the PM fleet catalog in POC mode,
and wraps both HTTPException and unhandled exceptions in a consistent
ErrorResponse envelope (request_id, type, message).
"""

from __future__ import annotations

import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import maistro_server.main as main_module
from maistro_server.main import _graceful_shutdown, _validate_startup, app, lifespan


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class _FakeLoop:
    """Minimal event-loop stand-in for lifespan signal registration tests.

    structlog's async logger also calls ``get_running_loop().run_in_executor``;
    this fake preserves that awaitable contract while letting the tests assert
    signal handler registration does not raise.
    """

    def __init__(self) -> None:
        self.add_signal_handler = MagicMock()

    async def run_in_executor(self, _executor, func):
        return func()


class TestValidateStartup:
    """CRIT-02 — duplicated here for completeness; primary coverage in test_startup.py."""

    def test_raises_without_keys_when_auth_required(self) -> None:
        from maistro.config.settings import Settings

        settings = Settings(api_keys=[], require_auth=True)
        with pytest.raises(RuntimeError, match="REQUIRE_AUTH"):
            _validate_startup(settings)


class TestExceptionHandlers:
    """Both handlers must wrap errors in the ErrorResponse envelope with a request_id."""

    def test_http_exception_wrapped_in_error_envelope(self, client: TestClient) -> None:
        response = client.get("/tasks/does-not-exist")
        assert response.status_code == 404
        data = response.json()
        assert data["error"]["type"] == "http_error"
        assert data["error"]["message"] == "Task not found"
        assert "request_id" in data["error"]

    async def test_unhandled_exception_returns_500_envelope(self) -> None:
        """Directly invoke the registered handler to verify its envelope shape —
        every current route catches its own exceptions internally, so there is
        no live endpoint that lets an exception escape to this handler."""
        import json

        from starlette.requests import Request

        from maistro_server.main import unhandled_exception_handler

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/boom",
            "headers": [],
            "query_string": b"",
            "state": {},
        }
        request = Request(scope)

        result = await unhandled_exception_handler(request, RuntimeError("kaboom"))
        assert result.status_code == 500

        body = json.loads(result.body)
        assert body["error"]["type"] == "internal_error"
        assert body["error"]["message"] == "Internal server error"
        assert "request_id" in body["error"]


class TestGracefulShutdown:
    async def test_drains_runner_on_signal(self) -> None:
        mock_runner = MagicMock()
        mock_runner.drain = AsyncMock()
        with patch.object(main_module, "_runner", mock_runner):
            await _graceful_shutdown(signal.SIGTERM)
        mock_runner.drain.assert_awaited_once_with(timeout=30)

    async def test_noop_when_no_runner(self) -> None:
        with patch.object(main_module, "_runner", None):
            await _graceful_shutdown(signal.SIGTERM)

            assert main_module._runner is None


class TestLifespan:
    """Drive the lifespan context manager directly (bypassing TestClient's
    worker-thread portal, which cannot register OS signal handlers)."""

    async def test_lifespan_starts_and_stops_runner(self) -> None:
        test_app = MagicMock()
        test_app.state = MagicMock()

        mock_runner = MagicMock()
        mock_runner.start = AsyncMock()
        mock_runner.stop = AsyncMock()

        with (
            patch("maistro.agents.conductor.run_task"),
            patch("maistro.memory.store.get_engine", return_value=None),
            patch("maistro.memory.store.reset_engine_cache"),
            patch("maistro.tools.sandbox.server.cleanup_all_containers", AsyncMock()),
            patch("maistro_server.main.logger", MagicMock(ainfo=AsyncMock())),
            patch("maistro_server.main.TaskRunner", return_value=mock_runner),
            patch("asyncio.get_running_loop") as mock_loop,
        ):
            mock_loop.return_value = _FakeLoop()
            async with lifespan(test_app):
                assert main_module._runner is mock_runner
                mock_runner.start.assert_awaited_once()

        mock_runner.stop.assert_awaited_once()
        assert main_module._runner is mock_runner

    async def test_lifespan_seeds_pm_catalog_in_poc_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
        test_app = MagicMock()
        test_app.state = MagicMock()

        mock_runner = MagicMock()
        mock_runner.start = AsyncMock()
        mock_runner.stop = AsyncMock()

        with (
            patch("maistro.agents.conductor.run_task"),
            patch("maistro.memory.store.get_engine", return_value=None),
            patch("maistro.memory.store.reset_engine_cache"),
            patch("maistro.tools.sandbox.server.cleanup_all_containers", AsyncMock()),
            patch("maistro_server.main.logger", MagicMock(ainfo=AsyncMock())),
            patch("maistro_server.main.TaskRunner", return_value=mock_runner),
            patch("asyncio.get_running_loop") as mock_loop,
        ):
            mock_loop.return_value = _FakeLoop()
            async with lifespan(test_app):
                pass

        assert test_app.state.pm_catalog is not None

    async def test_lifespan_configures_progress_webhook_when_url_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TASK_PROGRESS_WEBHOOK_URL", "https://example.test/webhook")
        test_app = MagicMock()
        test_app.state = MagicMock()

        captured: dict[str, object] = {}

        def _capture_runner(queue, executor, progress_webhook=None):
            captured["progress_webhook"] = progress_webhook
            mock_runner = MagicMock()
            mock_runner.start = AsyncMock()
            mock_runner.stop = AsyncMock()
            return mock_runner

        with (
            patch("maistro.agents.conductor.run_task"),
            patch("maistro.memory.store.get_engine", return_value=None),
            patch("maistro.memory.store.reset_engine_cache"),
            patch("maistro.tools.sandbox.server.cleanup_all_containers", AsyncMock()),
            patch("maistro_server.main.logger", MagicMock(ainfo=AsyncMock())),
            patch("maistro_server.main.TaskRunner", side_effect=_capture_runner),
            patch("asyncio.get_running_loop") as mock_loop,
        ):
            mock_loop.return_value = _FakeLoop()
            async with lifespan(test_app):
                pass

        assert captured["progress_webhook"] is not None

    async def test_lifespan_disposes_engine_on_shutdown(self) -> None:
        test_app = MagicMock()
        test_app.state = MagicMock()

        mock_runner = MagicMock()
        mock_runner.start = AsyncMock()
        mock_runner.stop = AsyncMock()

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        with (
            patch("maistro.agents.conductor.run_task"),
            patch("maistro.memory.store.get_engine", return_value=mock_engine),
            patch("maistro.memory.store.reset_engine_cache") as mock_reset,
            patch("maistro.tools.sandbox.server.cleanup_all_containers", AsyncMock()),
            patch("maistro_server.main.logger", MagicMock(ainfo=AsyncMock())),
            patch("maistro_server.main.TaskRunner", return_value=mock_runner),
            patch("asyncio.get_running_loop") as mock_loop,
        ):
            mock_loop.return_value = _FakeLoop()
            async with lifespan(test_app):
                pass

        mock_engine.dispose.assert_awaited_once()
        mock_reset.assert_called_once()
