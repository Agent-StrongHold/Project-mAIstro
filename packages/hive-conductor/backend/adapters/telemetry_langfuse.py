"""OpenTelemetry tracing — exports to Langfuse via OTLP.

Requires the `observability` extra (`pip install hive-conductor[observability]`,
which pulls `maistro-core[observability]`). Nothing here imports the Langfuse
SDK — the endpoint speaks OTLP — and the `langfuse` package was for a long time
the only telemetry dependency this app declared, while the OpenTelemetry
packages this adapter actually imports were declared nowhere (#514).

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
import threading
from collections.abc import Collection, Generator, Mapping
from contextlib import AbstractContextManager, contextmanager, suppress
from typing import Any, cast

from maistro.observability.telemetry_safety import (
    TelemetryTracer,
    mark_span_error,
    safe_exception_type_name,
    safe_span,
    set_allowlisted_span_attribute,
    set_span_attributes,
)
from protocols.telemetry import TelemetryPort

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
        BatchSpanProcessor,
    )
except Exception as exc:
    _OTEL_AVAILABLE = False
    _OTEL_IMPORT_ERROR_TYPE: type[BaseException] | None = type(exc)
else:
    _OTEL_AVAILABLE = True
    _OTEL_IMPORT_ERROR_TYPE = None

logger = logging.getLogger("hive.telemetry")

_tracer: TelemetryTracer | None = None
_initialization_attempted = False
_INITIALIZATION_LOCK = threading.Lock()

MISSING_PACKAGES = (
    "OTEL_EXPORTER_OTLP_ENDPOINT is set but OpenTelemetry could not be loaded "
    "(missing or incompatible), so no traces will be exported. Install or align "
    "the observability extra "
    "(hive-conductor[observability]), or build the image with "
    "--build-arg INSTALL_OBSERVABILITY=1."
)
INITIALIZATION_FAILED = "OpenTelemetry tracing could not be initialised"
RUNTIME_FAILED = "OpenTelemetry tracing failed; continuing without telemetry"
SPAN_ATTRIBUTE_FAILED = "OpenTelemetry span attribute write failed; continuing"
SPAN_CLOSE_FAILED = "OpenTelemetry span close failed; continuing"
SPAN_NAME_FAILED = "OpenTelemetry span name validation failed; using a fixed name"
SPAN_START_FAILED = "OpenTelemetry span start failed; continuing"
SPAN_STATUS_FAILED = "OpenTelemetry span status write failed; continuing"

_REPORT_LOCK = threading.Lock()
_REPORTED_CATEGORIES: set[str] = set()
_REPORTS: Mapping[str, tuple[int, str]] = {
    "initialization": (logging.ERROR, INITIALIZATION_FAILED),
    "missing_dependency": (logging.ERROR, MISSING_PACKAGES),
    "runtime": (logging.WARNING, RUNTIME_FAILED),
    "span_attribute_write": (logging.WARNING, SPAN_ATTRIBUTE_FAILED),
    "span_close": (logging.WARNING, SPAN_CLOSE_FAILED),
    "span_name": (logging.WARNING, SPAN_NAME_FAILED),
    "span_start": (logging.WARNING, SPAN_START_FAILED),
    "span_status_write": (logging.WARNING, SPAN_STATUS_FAILED),
}

_ALLOWED_SPAN_NAMES = frozenset({"chat_completion", "tool_call"})
_SAFE_INTEGER_METADATA = frozenset({"iteration", "retry_count", "tool_call_count"})
_SAFE_BOOLEAN_METADATA = frozenset({"streaming"})


def _report_once(category: str, error_type: type[BaseException]) -> None:
    """Best-effort once-per-category diagnostic containing no exception value."""
    report = _REPORTS.get(category)
    if report is None:
        return
    try:
        with _REPORT_LOCK:
            if category in _REPORTED_CATEGORIES:
                return
            _REPORTED_CATEGORIES.add(category)
        level, message = report
        logger.log(level, "%s (error_type=%s)", message, safe_exception_type_name(error_type))
    except Exception:
        return


def _shutdown_failed_initialization(
    provider: object | None,
    processor: object | None,
    *,
    processor_added: bool,
) -> None:
    """Best-effort cleanup for a processor allocated before setup failed."""
    provider_shutdown = getattr(provider, "shutdown", None)
    if processor_added and callable(provider_shutdown):
        try:
            provider_shutdown()
            return
        except Exception:
            pass
    processor_shutdown = getattr(processor, "shutdown", None)
    if callable(processor_shutdown):
        with suppress(Exception):
            processor_shutdown()


def _init_tracer() -> TelemetryTracer | None:
    global _initialization_attempted, _tracer
    if _tracer is not None:
        return _tracer

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        # Nobody asked for tracing. This is the ordinary state and says nothing.
        return None

    if _initialization_attempted:
        return None

    with _INITIALIZATION_LOCK:
        if _tracer is not None:
            return _tracer
        if _initialization_attempted:
            return None
        # Terminal before allocating anything: even a late setup failure is
        # one-shot, so concurrent/repeated calls cannot create processor threads.
        _initialization_attempted = True

        if not _OTEL_AVAILABLE:
            # An endpoint was configured and the optional stack cannot load.
            # Version-skew/runtime import failures are the same fail-open
            # deployment state as an absent package, but retain a safe type.
            _report_once("missing_dependency", _OTEL_IMPORT_ERROR_TYPE or ImportError)
            return None

        provider: Any | None = None
        processor: Any | None = None
        processor_added = False
        try:
            resource = Resource.create({"service.name": "fantasia-engine"})
            provider = TracerProvider(resource=resource)
            # SECURITY-REVIEW: External telemetry destination is
            # operator-controlled configuration, never request data; exported
            # fields are filtered below.
            exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            processor_added = True
            otel_trace.set_tracer_provider(provider)
            _tracer = cast(TelemetryTracer, otel_trace.get_tracer("fantasia.llm"))
        except Exception as exc:
            _shutdown_failed_initialization(
                provider,
                processor,
                processor_added=processor_added,
            )
            _report_once("initialization", type(exc))
            _tracer = None

        return _tracer


def _metadata_attributes(metadata: Mapping[str, Any] | None) -> dict[str, object]:
    """Select only bounded integer/boolean metadata fields."""
    if not metadata:
        return {}
    attributes: dict[str, object] = {}
    for key in _SAFE_INTEGER_METADATA:
        value = metadata.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            attributes[f"fantasia.{key}"] = value
    for key in _SAFE_BOOLEAN_METADATA:
        value = metadata.get(key)
        if isinstance(value, bool):
            attributes[f"fantasia.{key}"] = value
    return attributes


@contextmanager
def trace_llm(
    name: object,
    *,
    model: object = "",
    allowed_models: Collection[str] = (),
    user_id: object = "",
    metadata: Mapping[str, Any] | None = None,
    allowed_tool_names: Collection[str] = (),
) -> Generator[dict[str, Any], None, None]:
    """Create a content-free LLM span without changing the observed operation.

    The yielded mapping remains compatible with existing token/error producers,
    but prompt, completion, tool-call, result, and exception values are never
    exported. Only bounded counters/booleans, finite configured or registered
    labels, and generic error state are read.
    """
    ctx: dict[str, Any] = {}
    try:
        tracer = _init_tracer()
    except Exception as exc:
        _report_once("runtime", type(exc))
        tracer = None

    # SECURITY-REVIEW: This boundary intentionally excludes user IDs, prompts,
    # completions, tool arguments/results, exceptions, and stacks. The shared
    # policy PII-checks every remaining string before external export.
    with safe_span(
        tracer,
        name,
        allowed_names=_ALLOWED_SPAN_NAMES,
        reporter=_report_once,
    ) as span:
        try:
            attributes: dict[str, object] = {"gen_ai.system": "litellm"}
            if isinstance(user_id, str) and user_id:
                attributes["fantasia.user.present"] = True
            attributes.update(_metadata_attributes(metadata))
            set_span_attributes(span, attributes, reporter=_report_once)

            if not isinstance(model, str) or model:
                set_allowlisted_span_attribute(
                    span,
                    "gen_ai.request.model",
                    model,
                    allowed_models,
                    fallback="other",
                    reporter=_report_once,
                )

            if metadata is not None:
                missing = object()
                tool_name = metadata.get("tool_name", missing)
                if tool_name is not missing:
                    set_allowlisted_span_attribute(
                        span,
                        "fantasia.tool_name",
                        tool_name,
                        allowed_tool_names,
                        fallback="unregistered",
                        reporter=_report_once,
                    )
        except Exception as exc:
            _report_once("runtime", type(exc))

        try:
            yield ctx
        finally:
            try:
                tokens = ctx.get("tokens")
                if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
                    set_span_attributes(
                        span,
                        {"gen_ai.usage.total_tokens": tokens},
                        reporter=_report_once,
                    )
                if "error" in ctx:
                    mark_span_error(span, reporter=_report_once)
            except Exception as exc:
                _report_once("runtime", type(exc))


class LangfuseTelemetry(TelemetryPort):
    """The TelemetryPort implementation this app composes (#63).

    The port (`protocols.telemetry.TelemetryPort`) is the seam the chat path
    depends on; this class is the one backend wired today, delegating to this
    module's content-free spans. It is a wrapper rather than a rewrite: every
    allowlist, PII check and fail-open rule stays where it already lives and
    is already tested, and the port adds only the indirection that lets a
    deployment swap the backend without touching the chat service.

    Subclasses the Protocol explicitly so conformance is checked at class
    creation, not discovered missing at the first span.
    """

    def trace(self, **kwargs: Any) -> AbstractContextManager[Any]:
        """One generic span; `name` selects it (default the safe fallback)."""
        return trace_llm(kwargs.pop("name", "telemetry.operation"), **kwargs)

    def generation(self, **kwargs: Any) -> AbstractContextManager[Any]:
        """One LLM-generation span; `name` selects it."""
        return trace_llm(kwargs.pop("name", "telemetry.operation"), **kwargs)


#: The composed default. Call sites import this, not the concrete class, so
#: swapping backends is one line here and zero lines elsewhere.
telemetry: "LangfuseTelemetry" = LangfuseTelemetry()
