"""ADR-064 wiring tests.

Every assertion here goes through a real logging call. `redact()` itself is
already covered by `test_redact.py`, and that coverage is precisely what let the
gap survive: the function was correct and tested for months while nothing called
it. Testing the pipeline is the only thing that would have caught it, so nothing
in this file may call `redact()` directly.
"""

from __future__ import annotations

import io
import logging

import pytest

from maistro.security.log_redaction import (
    RedactingFormatter,
    install_log_redaction,
    structlog_redact_processor,
)

SECRET = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


@pytest.fixture
def captured() -> tuple[logging.Logger, io.StringIO]:
    """A private logger with one stream handler, redaction installed."""
    stream = io.StringIO()
    logger = logging.getLogger("maistro.test.redaction")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    install_log_redaction(("maistro.test.redaction",))
    return logger, stream


def test_secret_in_message_is_redacted(captured):
    logger, stream = captured
    logger.warning("calling upstream with %s", SECRET)
    out = stream.getvalue()
    assert SECRET not in out
    assert "[REDACTED_API_KEY]" in out


def test_secret_in_percent_arg_is_redacted(captured):
    """Formatting happens before redaction, so args are covered too — a
    filter-based implementation that only rewrote `record.msg` would leak here.
    """
    logger, stream = captured
    logger.info("token=%s user=%s", SECRET, "alice")
    out = stream.getvalue()
    assert SECRET not in out
    assert "alice" in out


def test_secret_in_traceback_is_redacted(captured):
    """The highest-value case: credentials most often surface in an exception's
    repr, which no message-level filter ever sees."""
    logger, stream = captured
    try:
        raise ValueError(f"connect failed: postgres://admin:{SECRET}@db:5432/app")
    except ValueError:
        logger.exception("upstream call failed")
    out = stream.getvalue()
    assert SECRET not in out
    assert "Traceback" in out


def test_non_secret_text_survives_intact(captured):
    logger, stream = captured
    logger.info("processed 42 items in 1.5s for tenant acme")
    assert "processed 42 items in 1.5s for tenant acme" in stream.getvalue()


def test_install_is_idempotent(captured):
    logger, _ = captured
    # The fixture already installed once; a second install must wrap nothing.
    assert install_log_redaction(("maistro.test.redaction",)) == 0
    formatter = logger.handlers[0].formatter
    assert isinstance(formatter, RedactingFormatter)
    assert not isinstance(formatter.inner, RedactingFormatter)


def test_handler_without_explicit_formatter_is_covered():
    """`Handler.formatter` is None until someone sets it; stdlib substitutes a
    default at format time. The wrapper has to materialise that default or the
    least-configured handler in the app is the one that leaks."""
    stream = io.StringIO()
    logger = logging.getLogger("maistro.test.redaction.bare")
    logger.handlers = []
    logger.propagate = False
    logger.addHandler(logging.StreamHandler(stream))
    install_log_redaction(("maistro.test.redaction.bare",))
    logger.error("key %s", SECRET)
    assert SECRET not in stream.getvalue()


def test_structlog_processor_redacts_string_values():
    event = {"event": f"auth failed for {SECRET}", "count": 3, "user": "alice"}
    out = structlog_redact_processor(None, "info", event)
    assert SECRET not in out["event"]
    assert out["count"] == 3
    assert out["user"] == "alice"


def test_structlog_processor_redacts_rendered_exception():
    """`format_exc_info` runs before this processor and leaves the traceback on
    the `exception` key as a plain string; that string is the leak path."""
    event = {"event": "boom", "exception": f'File "x.py", line 1\nAuthorization: Bearer {SECRET}'}
    out = structlog_redact_processor(None, "error", event)
    assert SECRET not in out["exception"]


def test_observability_configure_logging_installs_redaction():
    """The wiring, not the unit: configuring logging the way `maistro-server`
    does must leave redaction in place on the resulting handlers."""
    from maistro.observability.logging import configure_logging

    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        configure_logging(debug=True, json_output=False)
        assert any(isinstance(h.formatter, RedactingFormatter) for h in root.handlers)
    finally:
        root.handlers = saved
