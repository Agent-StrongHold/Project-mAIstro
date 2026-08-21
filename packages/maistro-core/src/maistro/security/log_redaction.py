"""Install `redact()` on the logging pipelines so secrets never reach a sink.

ADR-064 calls unredacted secrets in log output "the single highest-impact security
gap in the platform" and requires redaction "applied to all log output, error
messages, and trajectory recordings". SPEC-223 shipped the `redact()` function but
explicitly declared the wiring a non-goal, and no follow-up ever landed — so for
the whole life of the module every log line went out verbatim while SECURITY.md
and COMPLIANCE.md claimed otherwise. This module is that wiring.

Two sinks exist in this repo and both are covered here:

* **stdlib logging** — the Conductor (`hive-conductor/backend/logging_setup.py`).
  Covered by wrapping each *handler's* formatter, not by a logger-level filter:
  a `Filter` attached to a `Logger` is only consulted for records logged through
  that logger, never for records propagating up from child loggers, so the root
  filter that looks like it covers everything covers almost nothing. Handler-level
  formatting is the one point every emitted record passes through, and formatting
  the record first means the redaction also sees `%`-args and exception
  tracebacks, which is where credentials most often surface.

* **structlog** — `maistro.observability.logging`, used by `maistro-server`. A
  processor redacts the event dict before the renderer runs.

Both entry points are idempotent: `configure_logging()` is called more than once
in the Conductor (module import plus lifespan), and double-wrapping a formatter
would redact already-redacted text — harmless, but it makes the handler chain
impossible to reason about.
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

from maistro.security.redact import redact

__all__ = [
    "RedactingFormatter",
    "install_log_redaction",
    "structlog_redact_processor",
]

# Loggers whose handlers are wrapped by default. Uvicorn installs its own
# handlers that do not propagate to root (`propagate = False` in its dictConfig),
# so wrapping root alone would leave request logs and startup tracebacks — the
# lines most likely to carry a connection string — completely unredacted.
_DEFAULT_LOGGERS: tuple[str, ...] = (
    "",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
)


class RedactingFormatter(logging.Formatter):
    """Delegates to another formatter, then redacts the rendered string.

    Wrapping rather than subclassing the concrete formatter keeps whatever format
    string, date format, and `formatException` behaviour the application already
    configured; only the final text is touched.
    """

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self.inner = inner

    def format(self, record: logging.LogRecord) -> str:
        return redact(self.inner.format(record))

    # Delegated so callers that introspect the formatter (uvicorn's colourising
    # formatter does) still see the real implementation's answers.
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return self.inner.formatTime(record, datefmt)

    def formatException(self, ei: Any) -> str:
        return self.inner.formatException(ei)


def install_log_redaction(logger_names: tuple[str, ...] = _DEFAULT_LOGGERS) -> int:
    """Wrap the formatter of every handler on `logger_names`. Returns how many.

    Safe to call repeatedly: a handler whose formatter is already a
    `RedactingFormatter` is skipped. Handlers added *after* this call are not
    covered, so call it last in whatever configures logging.
    """
    wrapped = 0
    for name in logger_names:
        for handler in logging.getLogger(name).handlers:
            if isinstance(handler.formatter, RedactingFormatter):
                continue
            # A handler with no explicit formatter still formats, via a default
            # `Formatter()` created inside `logging.Handler.format`. Materialise
            # that default so the wrapper has something to delegate to.
            handler.setFormatter(RedactingFormatter(handler.formatter or logging.Formatter()))
            wrapped += 1
    return wrapped


def structlog_redact_processor(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """structlog processor: redact every string in the event dict, in place.

    Runs before the renderer so both the JSON and console renderers are covered.
    Non-string values are rendered by the renderer itself and cannot be redacted
    here without changing their type, so they are stringified only when they are
    already strings — an exception object, for example, is left to
    `format_exc_info`, which produces a string this processor then sees on the
    `exception` key.
    """
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = redact(value)
    return event_dict
