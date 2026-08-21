"""Agent tracing via OpenTelemetry — vendor-neutral.

Spans are emitted through the OpenTelemetry API, so any OTLP-compatible backend
(Arize/Phoenix, Langfuse, Honeycomb, Jaeger, …) can receive them by configuring an
exporter at application startup. With no TracerProvider/exporter configured, the OTel
API falls back to a no-op tracer and these decorators add negligible overhead. This
replaces the previous direct Langfuse SDK integration — the backend is now a
deployment choice (OTLP endpoint), not a hard dependency.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

import structlog

logger = structlog.get_logger()

P = ParamSpec("P")
T = TypeVar("T")


def _get_tracer() -> Any | None:
    """Return an OpenTelemetry tracer, or None if OpenTelemetry is not installed.

    Install the exporter stack via the `observability` extra to actually emit spans.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    return trace.get_tracer("maistro.agents")


def trace_agent(name: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Wrap an async agent call in an OpenTelemetry span.

    No-ops gracefully when OpenTelemetry is absent or no exporter is configured.
    """

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            tracer = _get_tracer()
            if tracer is None:
                return await fn(*args, **kwargs)  # type: ignore[misc,no-any-return]

            from opentelemetry.trace import Status, StatusCode

            with tracer.start_as_current_span(name) as span:
                try:
                    result = await fn(*args, **kwargs)  # type: ignore[misc]
                    span.set_attribute("maistro.output_preview", str(result)[:500])
                    return result  # type: ignore[no-any-return]
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator
