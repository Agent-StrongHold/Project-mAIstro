"""Repository-wide pytest compatibility hooks.

The workspace normally uses pytest-asyncio via the dev extra. Some constrained
scan environments can have pytest available before that plugin is installed. This
hook keeps async tests executable in those environments by running coroutine test
functions on a fresh event loop when no richer async plugin has handled them.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterator
from typing import Any

import pytest
import structlog


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register async-related pytest settings when pytest-asyncio is absent."""
    parser.addini("asyncio_mode", "Fallback async test mode for this repository")


def pytest_configure(config: pytest.Config) -> None:
    """Register markers and isolate ordinary tests from operator dotenv state."""
    config.addinivalue_line("markers", "asyncio: run an async test function")

    # The production Settings class intentionally loads `.env`, but the general
    # test suite must not inherit untracked operator configuration from the
    # repository root. Tests that exercise dotenv loading can still opt in with
    # Settings(_env_file=<isolated fixture path>), which overrides this class
    # default explicitly.
    from maistro.config.settings import Settings

    Settings.model_config["env_file"] = None


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Run coroutine test functions when pytest-asyncio is unavailable."""
    testfunction = pyfuncitem.obj
    if not inspect.iscoroutinefunction(testfunction):
        return None

    fixture_names = pyfuncitem._fixtureinfo.argnames
    testargs: dict[str, Any] = {
        name: pyfuncitem.funcargs[name] for name in fixture_names if name in pyfuncitem.funcargs
    }
    asyncio.run(testfunction(**testargs))
    return True


@pytest.fixture(autouse=True)
def _restore_structlog_global_config() -> Iterator[None]:
    """Undo any test's mutation of structlog's *global* configuration.

    `maistro.observability.logging.configure_logging()` is production code that
    reconfigures structlog process-wide, including
    `cache_logger_on_first_use=True`. Several tests reach it — directly in
    `observability/test_logging.py` and `security/test_log_redaction.py`, and
    indirectly through the maistro-server lifespan — and none restored it.

    With that flag left on, the next module-level `structlog.get_logger()`
    proxy to emit freezes itself permanently against the processor *list
    object* live at that instant. A later `reset_defaults()` installs a new
    list, and `structlog.testing.capture_logs()` — which mutates the current
    list in place — can then never reach the frozen logger. That is a test
    asserting on a log record it can no longer see, which is how
    `maistro-rsi/tests/test_persistence_integrity.py::test_mismatch_logs_error`
    failed in the full suite while passing alone: the record was emitted, as
    JSON on stderr, just not into the capture buffer.

    Restored with `configure(**saved)` rather than `reset_defaults()` on
    purpose — the latter allocates a fresh processor list and would reintroduce
    the very identity swap this exists to prevent.
    """
    saved = structlog.get_config().copy()
    try:
        yield
    finally:
        structlog.configure(**saved)
