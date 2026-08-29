"""OpenTelemetry tracing — exports to Langfuse via OTLP.

Requires the `observability` extra (`pip install hive-conductor[observability]`,
which pulls `maistro-core[observability]`). Nothing here imports the Langfuse
SDK — the endpoint speaks OTLP — and the `langfuse` package was for a long time
the only telemetry dependency this app declared, while the OpenTelemetry
packages `_init_tracer` actually imports were declared nowhere (#514). Their
absence is caught by the broad `except Exception` below and reported as
`_tracer = None`, which is indistinguishable from "tracing is switched off".

Env vars:
  OTEL_EXPORTER_OTLP_ENDPOINT  — Langfuse OTEL endpoint (e.g. https://cloud.langfuse.com/api/public/otel)
  OTEL_EXPORTER_OTLP_HEADERS   — "Authorization=Basic <base64(public_key:secret_key)>"

If neither is set, tracing is a no-op.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

_tracer = None


def _init_tracer():
    global _tracer
    if _tracer is not None:
        return _tracer

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "fantasia-engine"})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint + "/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("fantasia.llm")
    except Exception:
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
