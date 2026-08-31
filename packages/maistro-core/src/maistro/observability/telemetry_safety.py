"""Finite, content-free, fail-open policy for external telemetry spans.

Telemetry is an optional side effect. This module keeps that side effect from
changing the operation it observes and permits strings only when they come from
a finite server-owned allowlist. Prompts, results, tool payloads, user
identifiers, correlation values of unproven provenance, exceptions, and
tracebacks never cross this boundary.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from types import TracebackType
from typing import Any, Protocol

from maistro.observability.tiers import PIIDetector
from maistro.security.redact import redact as redact_secrets

try:
    from opentelemetry.trace import StatusCode as _StatusCode
except Exception:  # pragma: no cover - optional dependency may be version-skewed
    _STATUS_CODE_ERROR: Any | None = None
else:
    _STATUS_CODE_ERROR = _StatusCode.ERROR

TelemetryAttribute = str | bool | int
TelemetryFailureReporter = Callable[[str, type[BaseException]], None]

_LOW_CARDINALITY_LABEL = re.compile(r"[a-z0-9][a-z0-9_.:/-]{0,127}")
_MAX_ALLOWLIST_SIZE = 128
_MAX_INTEGER_ATTRIBUTE = 2**63 - 1
_REDACTED_LABEL = "redacted"
_STABLE_FALLBACK_LABELS = frozenset({"agent.call", "other", "telemetry.operation", "unregistered"})
_FIXED_STRING_ATTRIBUTES: Mapping[str, frozenset[str]] = {
    "error.type": frozenset({"application_error"}),
    "gen_ai.system": frozenset({"litellm"}),
}
_DYNAMIC_STRING_ATTRIBUTES = frozenset({"fantasia.tool_name", "gen_ai.request.model"})
_BOOLEAN_ATTRIBUTES = frozenset({"fantasia.streaming", "fantasia.user.present"})
_INTEGER_ATTRIBUTE_RANGES: Mapping[str, tuple[int, int]] = {
    "fantasia.iteration": (0, 5),
    "fantasia.retry_count": (0, 10),
    "fantasia.tool_call_count": (0, 128),
    "gen_ai.usage.total_tokens": (0, _MAX_INTEGER_ATTRIBUTE),
}
_PII_DETECTOR = PIIDetector(mode="prod")

logger = logging.getLogger("maistro.telemetry")
_REPORT_LOCK = threading.Lock()
_REPORTED_FAILURE_CATEGORIES: set[str] = set()
_FAILURE_MESSAGES: Mapping[str, str] = {
    "span_attribute_write": "OpenTelemetry span attribute write failed; continuing",
    "span_close": "OpenTelemetry span close failed; continuing",
    "span_name": "OpenTelemetry span name validation failed; using a fixed name",
    "span_start": "OpenTelemetry span start failed; continuing",
    "span_status_write": "OpenTelemetry span status write failed; continuing",
    "tracer_lookup": "OpenTelemetry tracer lookup failed; continuing",
}


class TelemetrySpan(Protocol):
    """The small OpenTelemetry span surface used by the safety boundary."""

    def set_attribute(self, key: str, value: TelemetryAttribute) -> Any: ...

    def set_status(self, status: Any, description: str | None = None) -> Any: ...


class _SpanContextManager(Protocol):
    def __enter__(self) -> TelemetrySpan: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Any: ...


class TelemetryTracer(Protocol):
    """The tracer operation needed to create one protected span."""

    def start_as_current_span(
        self,
        name: str,
        *,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ) -> _SpanContextManager: ...


def safe_exception_type_name(error_type: type[BaseException]) -> str:
    """Map an exception class to one finite, non-payload diagnostic name."""
    safe_bases: tuple[type[Exception], ...] = (
        ModuleNotFoundError,
        ImportError,
        TimeoutError,
        ConnectionError,
        PermissionError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        AttributeError,
        LookupError,
        Exception,
    )
    try:
        for safe_base in safe_bases:
            if issubclass(error_type, safe_base):
                return safe_base.__name__
    except Exception:
        return "Exception"
    return "Exception"


def report_telemetry_failure(category: str, error_type: type[BaseException]) -> None:
    """Warn once for a known failure category without rendering an exception."""
    message = _FAILURE_MESSAGES.get(category)
    if message is None:
        return
    try:
        with _REPORT_LOCK:
            if category in _REPORTED_FAILURE_CATEGORIES:
                return
            _REPORTED_FAILURE_CATEGORIES.add(category)
        logger.warning("%s (error_type=%s)", message, safe_exception_type_name(error_type))
    except Exception:
        # A diagnostic about broken telemetry is itself optional telemetry.
        return


def _notify_failure(
    reporter: TelemetryFailureReporter | None,
    category: str,
    error: Exception,
) -> None:
    try:
        (reporter or report_telemetry_failure)(category, type(error))
    except Exception:
        return


def _normalized_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        if not value or len(value) > 128:
            return None
        # SECURITY-REVIEW: ``scan`` is side-effect free. ``inspect`` would
        # increment the unexpected-PII application metric for rejected
        # telemetry labels, allowing telemetry traffic to distort that metric.
        if _PII_DETECTOR.scan(value):
            return None
        if redact_secrets(value) != value:
            return None
        normalized = value.lower()
    except Exception:
        return None
    if _LOW_CARDINALITY_LABEL.fullmatch(normalized) is None:
        return None
    return normalized


def sanitize_telemetry_label(value: object) -> str:
    """Normalize a label lexically, or return one fixed redaction marker.

    This check removes PII, secrets, case-based encoding, and malformed values.
    It does *not* grant cardinality approval; external writes must additionally
    pass through an explicit finite allowlist below.
    """
    return _normalized_label(value) or _REDACTED_LABEL


def _select_allowlisted_label(
    value: object,
    allowed_values: Collection[str],
) -> str | None:
    candidate = _normalized_label(value)
    if candidate is None:
        return None
    normalized_allowed: set[str] = set()
    try:
        for index, allowed in enumerate(allowed_values):
            if index >= _MAX_ALLOWLIST_SIZE:
                return None
            normalized = _normalized_label(allowed)
            if normalized is not None:
                normalized_allowed.add(normalized)
    except Exception:
        return None
    return candidate if candidate in normalized_allowed else None


def allowlisted_telemetry_label(
    value: object,
    allowed_values: Collection[str],
    *,
    fallback: str,
) -> str:
    """Return a normalized allowlisted value or one stable finite sentinel."""
    safe_fallback = _normalized_label(fallback)
    if safe_fallback not in _STABLE_FALLBACK_LABELS:
        safe_fallback = "other"
    return _select_allowlisted_label(value, allowed_values) or safe_fallback


def _write_span_attribute(
    span: TelemetrySpan,
    key: str,
    value: TelemetryAttribute,
    reporter: TelemetryFailureReporter | None,
) -> None:
    try:
        # SECURITY-REVIEW: This is the sole external span-attribute write.
        span.set_attribute(key, value)
    except Exception as exc:
        _notify_failure(reporter, "span_attribute_write", exc)


def set_span_attributes(
    span: TelemetrySpan | None,
    attributes: Mapping[str, object],
    *,
    reporter: TelemetryFailureReporter | None = None,
) -> None:
    """Best-effort export of fixed strings and bounded numeric attributes."""
    if span is None:
        return
    for key, value in attributes.items():
        safe_value: TelemetryAttribute | None = None
        if isinstance(value, str):
            allowed = _FIXED_STRING_ATTRIBUTES.get(key)
            if allowed is not None:
                safe_value = _select_allowlisted_label(value, allowed)
        elif isinstance(value, bool):
            if key in _BOOLEAN_ATTRIBUTES:
                safe_value = value
        elif isinstance(value, int):
            limits = _INTEGER_ATTRIBUTE_RANGES.get(key)
            if limits is not None and limits[0] <= value <= limits[1]:
                safe_value = value
        if safe_value is not None:
            _write_span_attribute(span, key, safe_value, reporter)


def set_allowlisted_span_attribute(
    span: TelemetrySpan | None,
    key: str,
    value: object,
    allowed_values: Collection[str],
    *,
    fallback: str,
    reporter: TelemetryFailureReporter | None = None,
) -> None:
    """Write one dynamic string only after finite allowlist selection."""
    if span is None or key not in _DYNAMIC_STRING_ATTRIBUTES:
        return
    safe_value = allowlisted_telemetry_label(value, allowed_values, fallback=fallback)
    _write_span_attribute(span, key, safe_value, reporter)


def mark_span_error(
    span: TelemetrySpan | None,
    *,
    reporter: TelemetryFailureReporter | None = None,
) -> None:
    """Mark an application error without exporting its exception or stack."""
    if span is None:
        return
    set_span_attributes(span, {"error.type": "application_error"}, reporter=reporter)
    if _STATUS_CODE_ERROR is None:
        return
    try:
        span.set_status(_STATUS_CODE_ERROR)
    except Exception as exc:
        _notify_failure(reporter, "span_status_write", exc)


def _close_span(
    manager: _SpanContextManager,
    reporter: TelemetryFailureReporter | None,
) -> None:
    try:
        # Always close as a clean context. Passing an application exception to
        # OpenTelemetry would trigger vendor/default exception and stack export.
        manager.__exit__(None, None, None)
    except Exception as exc:
        _notify_failure(reporter, "span_close", exc)


@contextmanager
def safe_span(
    tracer: TelemetryTracer | None,
    name: object,
    *,
    allowed_names: Collection[str],
    fallback_name: str = "telemetry.operation",
    reporter: TelemetryFailureReporter | None = None,
) -> Iterator[TelemetrySpan | None]:
    """Yield a finite-name span whose lifecycle cannot alter the caller.

    Application exceptions are re-raised unchanged after a generic error marker
    is attempted. They are deliberately never handed to the telemetry context
    manager, which prevents automatic exception-event and traceback capture.
    """
    manager: _SpanContextManager | None = None
    span: TelemetrySpan | None = None

    if tracer is not None:
        try:
            # Name selection belongs inside the non-interference boundary:
            # decorators and adapters are callable Python APIs, so runtime
            # callers can violate their annotations.
            safe_name = allowlisted_telemetry_label(
                name,
                allowed_names,
                fallback=fallback_name,
            )
        except Exception as exc:
            _notify_failure(reporter, "span_name", exc)
            safe_name = "telemetry.operation"
        try:
            # SECURITY-REVIEW: Disable OpenTelemetry's automatic exception
            # recording at the external exporter boundary.
            manager = tracer.start_as_current_span(
                safe_name,
                record_exception=False,
                set_status_on_exception=False,
            )
            span = manager.__enter__()
        except Exception as exc:
            _notify_failure(reporter, "span_start", exc)
            manager = None
            span = None

    try:
        yield span
    except BaseException:
        mark_span_error(span, reporter=reporter)
        raise
    finally:
        if manager is not None:
            _close_span(manager, reporter)


__all__ = [
    "TelemetryFailureReporter",
    "TelemetrySpan",
    "TelemetryTracer",
    "allowlisted_telemetry_label",
    "mark_span_error",
    "report_telemetry_failure",
    "safe_exception_type_name",
    "safe_span",
    "sanitize_telemetry_label",
    "set_allowlisted_span_attribute",
    "set_span_attributes",
]
