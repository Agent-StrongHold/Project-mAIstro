"""Structured logging configuration.

Configures structlog with JSON output for production and
pretty console output for development. Call configure_logging()
once during application startup.
"""

from __future__ import annotations

import logging
import sys

import structlog

from maistro.observability.correlation import execution_context_processor
from maistro.security.log_redaction import install_log_redaction, structlog_redact_processor


def configure_logging(*, debug: bool = False, json_output: bool = True) -> None:
    """Configure structlog and stdlib logging for the application.

    Args:
        debug: Enable DEBUG level (default: WARNING in prod, DEBUG in dev)
        json_output: Use JSON renderer (True for production) or console renderer (False for dev)
    """
    log_level = logging.DEBUG if debug else logging.WARNING

    # Shared processors for both structlog and stdlib
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        # After `merge_contextvars`, so a caller that bound an id through
        # structlog directly still wins over the ambient execution context —
        # `execution_context_processor` uses `setdefault` (#707).
        execution_context_processor,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if json_output and not debug:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            # ADR-064: last processor before the renderer, so it sees the
            # traceback string `format_exc_info` just produced as well as the
            # event's own fields. Anything added after this point would bypass it.
            structlog_redact_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging to route through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )
    # Quiet noisy third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access", "docker", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Third-party libraries log through stdlib, not structlog, so the processor
    # above never sees them. Handler wrapping is what covers httpx's request
    # lines and any traceback uvicorn prints. Must come after basicConfig —
    # there are no handlers to wrap before it.
    install_log_redaction()
