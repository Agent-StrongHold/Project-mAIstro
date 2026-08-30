"""OpenTelemetry tracing — exports to Langfuse via OTLP.

Requires the `observability` extra (`pip install hive-conductor[observability]`,
which pulls `maistro-core[observability]`). Nothing here imports the Langfuse
SDK — the endpoint speaks OTLP — and the `langfuse` package was for a long time
the only telemetry dependency this app declared, while the OpenTelemetry
packages `_init_tracer` actually imports were declared nowhere (#514).

Their absence used to be caught by the broad `except Exception` below and
reported as `_tracer = None` — the same value that means "no endpoint is
configured", so an operator who *had* configured one saw no traces, no error,
and no way to tell the two apart (#668). The two are now distinguished: a
missing package is reported at error level, naming the extra to install.

Env vars:
  OTEL_EXPORTER_OTLP_ENDPOINT  — Langfuse OTEL endpoint (e.g. https://cloud.langfuse.com/api/public/otel)
  OTEL_EXPORTER_OTLP_HEADERS   — "Authorization=Basic <base64(public_key:secret_key)>"

If neither is set, tracing is a no-op.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("hive.telemetry")

#: Said once per process. `_init_tracer` runs on every traced call, and a line
#: per LLM request would bury the one time it mattered under its own repetition.
_reported = False

_tracer = None

MISSING_PACKAGES = (
    "OTEL_EXPORTER_OTLP_ENDPOINT is set but OpenTelemetry is not installed, so "
    "no traces will be exported. Install the observability extra "
    "(hive-conductor[observability]), or build the image with "
    "--build-arg INSTALL_OBSERVABILITY=1."
)


def _init_tracer():
    global _tracer, _reported
    if _tracer is not None:
        return _tracer

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        # Nobody asked for tracing. This is the ordinary state and says nothing.
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        # Ahead of the broad clause, and separate from it: an endpoint was
        # configured and the packages to honour it are absent. Folded into
        # `except Exception` this returned the same `None` that means "tracing
        # is off", so a deployment that had asked for traces was told nothing
        # at all -- the one failure mode a telemetry adapter must not have.
        if not _reported:
            logger.error(MISSING_PACKAGES)
            _reported = True
        return None

    try:
        resource = Resource.create({"service.name": "fantasia-engine"})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint + "/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("fantasia.llm")
    except Exception:
        # The packages are here and setting them up still failed -- a bad
        # endpoint, a refused exporter. Also worth saying, and a different
        # thing to say.
        if not _reported:
            logger.exception("OpenTelemetry tracing could not be initialised")
            _reported = True
        _tracer = None

    return _tracer


@contextmanager
def trace_llm(  # noqa: C901  many independent optional attributes
    name: str,
    *,
    model: str = "",
    user_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Context manager that creates a span for an LLM call. Attach input/output via the yielded dict."""
    tracer = _init_tracer()
    ctx: dict[str, Any] = {}

    if tracer is None:
        yield ctx
        return

    from opentelemetry import trace

    with tracer.start_as_current_span(name) as span:
        span.set_attribute("gen_ai.system", "litellm")
        if model:
            span.set_attribute("gen_ai.request.model", model)
        if user_id:
            span.set_attribute("user.id", user_id)
        if metadata:
            for k, v in metadata.items():
                span.set_attribute(f"fantasia.{k}", str(v))

        yield ctx

        if ctx.get("input"):
            span.set_attribute("gen_ai.prompt", str(ctx["input"])[:4000])
        if ctx.get("output"):
            span.set_attribute("gen_ai.completion", str(ctx["output"])[:4000])
        if ctx.get("tool_calls"):
            span.set_attribute("fantasia.tool_calls", str(ctx["tool_calls"]))
        if ctx.get("tokens"):
            span.set_attribute("gen_ai.usage.total_tokens", ctx["tokens"])
        if ctx.get("error"):
            span.set_status(trace.StatusCode.ERROR, ctx["error"])
