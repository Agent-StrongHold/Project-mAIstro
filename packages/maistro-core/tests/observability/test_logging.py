"""Coverage for observability/logging.py."""

from __future__ import annotations

import asyncio
import io
import logging

import pytest
import structlog

from maistro.observability.logging import configure_logging
from maistro.security.log_redaction import RedactingFormatter


def test_configure_logging_json_output_uses_json_renderer() -> None:
    configure_logging(debug=False, json_output=True)
    config = structlog.get_config()
    renderers = [type(p).__name__ for p in config["processors"]]
    assert "JSONRenderer" in renderers


def test_configure_logging_debug_uses_console_renderer_even_if_json_requested() -> None:
    configure_logging(debug=True, json_output=True)
    config = structlog.get_config()
    renderers = [type(p).__name__ for p in config["processors"]]
    assert "ConsoleRenderer" in renderers


def test_configure_logging_non_json_uses_console_renderer() -> None:
    configure_logging(debug=False, json_output=False)
    config = structlog.get_config()
    renderers = [type(p).__name__ for p in config["processors"]]
    assert "ConsoleRenderer" in renderers


def test_configure_logging_quiets_noisy_third_party_loggers() -> None:
    configure_logging(debug=True)
    for noisy in ("httpx", "httpcore", "uvicorn.access", "docker", "asyncio"):
        assert logging.getLogger(noisy).level == logging.WARNING


def _through_configured_chain(event: str) -> dict[str, object]:
    """Run one record through the chain `configure_logging` actually installed.

    Calling `structlog.contextvars.merge_contextvars` directly would assert a
    stdlib property and pass even if `configure_logging` never installed it —
    a test of somebody else's library wearing our module's name. Reading the
    processors back out of the live config is what ties the assertion to our
    code.
    """
    record: dict[str, object] = {"event": event}
    for processor in structlog.get_config()["processors"]:
        if isinstance(record, dict) and processor is structlog.contextvars.merge_contextvars:
            record = processor(None, "info", record)
    return record


@pytest.mark.ac("SPEC-228/AC-1")
def test_configured_chain_merges_bound_context_and_honours_clear() -> None:
    configure_logging(debug=False, json_output=True)
    assert structlog.contextvars.merge_contextvars in structlog.get_config()["processors"]

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="r-1")
    try:
        assert _through_configured_chain("x")["request_id"] == "r-1"
    finally:
        structlog.contextvars.clear_contextvars()
    assert "request_id" not in _through_configured_chain("x")


@pytest.mark.ac("SPEC-228/AC-1")
async def test_bound_context_does_not_leak_between_concurrent_requests() -> None:
    """Request scoping is only real if two in-flight requests cannot see each other.

    Routed through the configured chain rather than the contextvars API, so a
    chain rebuilt around a module-level dict — which would satisfy every other
    test in this file — fails here.
    """
    configure_logging(debug=False, json_output=True)
    structlog.contextvars.clear_contextvars()
    seen: dict[str, dict[str, object]] = {}

    async def request(name: str) -> None:
        structlog.contextvars.bind_contextvars(request_id=name)
        await asyncio.sleep(0)  # yield, so both requests are bound at once
        seen[name] = _through_configured_chain("handled")

    await asyncio.gather(request("r-1"), request("r-2"))

    assert seen["r-1"]["request_id"] == "r-1"
    assert seen["r-2"]["request_id"] == "r-2"


def test_configure_logging_installs_the_stdlib_correlation_formatter() -> None:
    """The wiring, not the formatter.

    `install_log_correlation` has its own tests; this is the one that fails if
    `configure_logging` stops calling it. A mutation removing that call survived
    every other test in this change, which is exactly the "wired but never read"
    shape #236 exists to catch (#707).
    """
    from maistro.observability.correlation import (
        CorrelatingFormatter,
        bind_execution_context,
    )

    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.handlers = [handler]

        configure_logging(debug=True, json_output=False)

        assert isinstance(handler.formatter, CorrelatingFormatter | RedactingFormatter)
        with bind_execution_context(run_id="r-wired"):
            logging.getLogger("maistro.test.wiring").warning("through the stdlib")
        assert "run_id=r-wired" in stream.getvalue()
    finally:
        root.handlers = saved
