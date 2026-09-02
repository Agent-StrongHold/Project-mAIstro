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
from typing import ParamSpec, TypeVar, cast

from maistro.observability.telemetry_safety import (
    TelemetryTracer,
    report_telemetry_failure,
    safe_span,
)

try:
    from opentelemetry import trace as _otel_trace
except Exception:
    _otel_trace = None  # type: ignore[assignment]  # supported without observability extra

P = ParamSpec("P")
T = TypeVar("T")

_AGENT_SPAN_NAMES = frozenset({"conductor"})


def _get_tracer() -> TelemetryTracer | None:
    """Return an OpenTelemetry tracer, or None if OpenTelemetry is not installed.

    Install the exporter stack via the `observability` extra to actually emit spans.
    """
    if _otel_trace is None:
        return None
    try:
        return cast(TelemetryTracer, _otel_trace.get_tracer("maistro.agents"))
    except Exception as exc:
        # Tracer lookup is telemetry setup, not part of the product operation.
        report_telemetry_failure("tracer_lookup", type(exc))
        return None


def trace_agent(name: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Wrap an async agent call in an OpenTelemetry span.

    No-ops gracefully when OpenTelemetry is absent or no exporter is configured.
    """

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                tracer = _get_tracer()
            except Exception as exc:
                report_telemetry_failure("tracer_lookup", type(exc))
                tracer = None
            # SECURITY-REVIEW: Agent results and exceptions can contain prompts,
            # secrets, and tool payloads. Ambient ids are also excluded because
            # their external-export provenance is not represented by the
            # execution ContextVar (HTTP request ids may be client supplied).
            with safe_span(
                tracer,
                name,
                allowed_names=_AGENT_SPAN_NAMES,
                fallback_name="agent.call",
            ):
                return await fn(*args, **kwargs)  # type: ignore[misc,no-any-return]

        return wrapper  # type: ignore[return-value]

    return decorator
