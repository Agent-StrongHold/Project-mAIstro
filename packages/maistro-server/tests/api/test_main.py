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


def _stopped_runner() -> MagicMock:
    runner = MagicMock()
    runner.start = AsyncMock()
    runner.stop = AsyncMock()
    return runner


class TestLifespan:
    """Drive the lifespan context manager directly (bypassing TestClient's
    worker-thread portal, which cannot register OS signal handlers)."""

    @pytest.fixture(autouse=True)
    def _no_database_configured(self, monkeypatch: pytest.MonkeyPatch):
        """These tests are about the runner, the webhook and the engine.

        The lifespan also builds a spine pool now (#132), and it resolves which
        database from the environment (#187) -- so a developer who happens to
        export `DATABASE_URL` or the `DB_*` set made these three tests reach for
        a real server and fail for a reason none of them is about. Clearing the
        whole resolver input keeps them answering their own question.
        """
        for name in ("DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
            monkeypatch.delenv(name, raising=False)
        # And the lifespan now builds a Container (#142), which
        # `_validate_startup` refuses to do without a router key. Same
        # reasoning as the database above: these tests are not about that
        # check, and `test_startup.py` is.
        monkeypatch.setenv("ROUTER_API_KEY", "test-router-key")

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
            patch("maistro_server.main.logger", MagicMock(ainfo=AsyncMock(), awarning=AsyncMock())),
            patch("maistro_server.main.TaskRunner", return_value=mock_runner),
            patch("asyncio.get_running_loop") as mock_loop,
        ):
            mock_loop.return_value = _FakeLoop()
            async with lifespan(test_app):
                assert main_module._runner is mock_runner
                mock_runner.start.assert_awaited_once()

        mock_runner.stop.assert_awaited_once()
        assert main_module._runner is mock_runner

    @pytest.mark.parametrize(
        ("pool", "expects_warning"),
        [
            pytest.param(None, True, id="no-database"),
            pytest.param(object(), False, id="postgres-pool"),
        ],
    )
    async def test_the_lifespan_says_which_run_store_is_live(
        self, pool: object, expects_warning: bool
    ) -> None:
        """Both halves of the spine branch, and the log line is the point.

        `None` is an ordinary answer rather than a degraded one, so it warns:
        a Run admitted by `/tasks` is lost on restart, and an operator who
        configured no database should be told that rather than left to assume
        otherwise. With a pool there is nothing to warn about, and a warning
        left behind would say the opposite of what is true.
        """
        test_app = MagicMock()
        test_app.state = MagicMock()
        server_logger = MagicMock(ainfo=AsyncMock(), awarning=AsyncMock())

        with (
            patch("maistro.agents.conductor.run_task"),
            patch("maistro.memory.store.get_engine", return_value=None),
            patch("maistro.memory.store.reset_engine_cache"),
            patch("maistro.tools.sandbox.server.cleanup_all_containers", AsyncMock()),
            patch("maistro_server.main.logger", server_logger),
            patch("maistro_server.main._run_store_pool", AsyncMock(return_value=pool)),
            # The spine now comes from the Container (#142), so this stands in
            # for the Container rather than for `wire_execution_spine`. Still
            # stubbed for the same reason: this test is about which log line
            # the branch emits, not about wiring a real one.
            patch(
                "maistro_server.main._build_container",
                AsyncMock(return_value=MagicMock()),
            ),
            patch("maistro_server.main.TaskRunner", return_value=_stopped_runner()),
            patch("asyncio.get_running_loop") as mock_loop,
        ):
            mock_loop.return_value = _FakeLoop()
            async with lifespan(test_app):
                pass

        warned = [
            call
            for call in server_logger.awarning.await_args_list
            if call.args and call.args[0] == "run_store_in_process_only"
        ]
        assert bool(warned) is expects_warning

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
            patch("maistro_server.main.logger", MagicMock(ainfo=AsyncMock(), awarning=AsyncMock())),
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

        def _capture_runner(queue, executor, progress_webhook=None, attempts=None):
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
            patch("maistro_server.main.logger", MagicMock(ainfo=AsyncMock(), awarning=AsyncMock())),
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
            patch("maistro_server.main.logger", MagicMock(ainfo=AsyncMock(), awarning=AsyncMock())),
            patch("maistro_server.main.TaskRunner", return_value=mock_runner),
            patch("asyncio.get_running_loop") as mock_loop,
        ):
            mock_loop.return_value = _FakeLoop()
            async with lifespan(test_app):
                pass

        mock_engine.dispose.assert_awaited_once()
        mock_reset.assert_called_once()


class TestRunStorePool:
    """`_run_store_pool` decides whether this deployment gets a durable spine.

    Both answers matter and neither had a test. `None` is ordinary — no
    database configured means the in-process store and a log line saying so —
    while a PostgreSQL URL must reach `get_pool` through the *same* resolver
    alembic uses (#187), or the spine lands in a database the migrations never
    described.
    """

    @pytest.fixture(autouse=True)
    def _clean_environment(self, monkeypatch: pytest.MonkeyPatch):
        for name in ("DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
            monkeypatch.delenv(name, raising=False)
        # And the lifespan now builds a Container (#142), which
        # `_validate_startup` refuses to do without a router key. Same
        # reasoning as the database above: these tests are not about that
        # check, and `test_startup.py` is.
        monkeypatch.setenv("ROUTER_API_KEY", "test-router-key")

    async def test_no_database_configured_is_none_not_an_error(self) -> None:
        assert await main_module._run_store_pool() is None

    @pytest.mark.parametrize("url", ["sqlite:///tmp/x.db", "memory://"])
    async def test_a_non_postgres_backend_gets_no_pool(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        """Neither can hold the spine, and neither is a misconfiguration."""
        monkeypatch.setenv("DATABASE_URL", url)

        assert await main_module._run_store_pool() is None

    async def test_a_postgres_url_opens_a_pool_on_the_normalised_dsn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The `+driver` spelling is SQLAlchemy's; asyncpg speaks libpq DSNs.
        Passing it through unchanged fails on the scheme rather than connecting.
        """
        seen: list[str] = []
        sentinel = object()

        async def _fake_get_pool(dsn: str):
            seen.append(dsn)
            return sentinel

        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/maistro")
        monkeypatch.setattr("maistro.persistence.get_pool", _fake_get_pool)

        assert await main_module._run_store_pool() is sentinel
        assert seen == ["postgresql://u:p@db:5432/maistro"]

    async def test_the_db_star_variables_reach_it_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`docker-compose.yml` sets these and no DATABASE_URL (#187). A spine
        that only read DATABASE_URL would run in-process on the shipped
        default, beside a PostgreSQL container with a volume."""
        seen: list[str] = []

        async def _fake_get_pool(dsn: str):
            seen.append(dsn)
            return object()

        for name, value in (
            ("DB_HOST", "db"),
            ("DB_PORT", "5432"),
            ("DB_NAME", "maistro"),
            ("DB_USER", "maistro"),
            ("DB_PASSWORD", "maistro"),
        ):
            monkeypatch.setenv(name, value)
        monkeypatch.setattr("maistro.persistence.get_pool", _fake_get_pool)

        assert await main_module._run_store_pool() is not None
        assert seen and seen[0].startswith("postgresql://")
        assert "db:5432/maistro" in seen[0]
