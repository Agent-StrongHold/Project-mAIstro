"""The Conductor's half of the ADR-064 wiring.

Drives `configure_logging()` — the function the app actually calls — rather than
`install_log_redaction()`. The gap this closes was a correct, tested function
with no caller, so a test that calls the primitive proves nothing about the app.
"""

from __future__ import annotations

import io
import logging

import logging_setup
from logging_setup import OAuthCallbackQueryFilter

SECRET = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
_PROVIDER = "test"
_CALLBACK_PATH = f"/v1/auth/oauth/{_PROVIDER}/callback"


def _reconfigure(monkeypatch) -> io.StringIO:
    """Run the app's real `configure_logging()` against a captured root handler."""
    stream = io.StringIO()
    root = logging.getLogger()
    saved = list(root.handlers)
    root.handlers = [logging.StreamHandler(stream)]
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False, raising=False)
    monkeypatch.setattr(logging_setup, "_REDACTION_ACTIVE", False, raising=False)
    logging_setup.configure_logging()
    monkeypatch.setattr(logging, "_maistro_saved_handlers", saved, raising=False)
    return stream


def test_configure_logging_redacts_root_output(monkeypatch):
    stream = _reconfigure(monkeypatch)
    root = logging.getLogger()
    try:
        logging.getLogger("hive.test").error("provider rejected key %s", SECRET)
        out = stream.getvalue()
        assert SECRET not in out
        assert "[REDACTED_API_KEY]" in out
    finally:
        root.handlers = getattr(logging, "_maistro_saved_handlers", [])


def test_configure_logging_reports_redaction_active(monkeypatch):
    root = logging.getLogger()
    _reconfigure(monkeypatch)
    try:
        assert logging_setup.redaction_active() is True
    finally:
        root.handlers = getattr(logging, "_maistro_saved_handlers", [])


def test_oauth_callback_filter_sanitizes_string_message() -> None:
    secret = "sentinel-msg-code-material"
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f'GET {_CALLBACK_PATH}?code={secret} HTTP/1.1" 303',
        args=(),
        exc_info=None,
    )

    assert OAuthCallbackQueryFilter().filter(record) is True
    assert secret not in record.msg
    assert _CALLBACK_PATH in record.msg
    assert "?code=" not in record.msg


def test_oauth_callback_filter_skips_non_string_message() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ignored",
        args=(),
        exc_info=None,
    )
    record.msg = 404

    assert OAuthCallbackQueryFilter().filter(record) is True
    assert record.msg == 404


def test_oauth_callback_filter_skips_non_tuple_non_dict_args() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="plain access log",
        args=None,
        exc_info=None,
    )

    assert OAuthCallbackQueryFilter().filter(record) is True
    assert record.args is None


def test_oauth_callback_filter_preserves_non_string_format_args() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="%s %s",
        args=("127.0.0.1:1", 303),
        exc_info=None,
    )

    assert OAuthCallbackQueryFilter().filter(record) is True
    assert record.args == ("127.0.0.1:1", 303)


def test_health_publishes_redaction_state(authed_client):
    """A degraded control has to be visible, not inferred from source (F3)."""
    body = authed_client.get("/health").json()
    # True, not merely present: a key that reports False when the control is in
    # fact installed would be its own honesty bug, and asserting only presence
    # is what lets an always-False probe pass forever.
    assert body["log_redaction_active"] is True
    assert authed_client.get("/health/ready").json()["checks"]["log_redaction"] is True
