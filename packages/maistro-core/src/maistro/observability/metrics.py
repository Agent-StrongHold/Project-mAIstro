"""Dependency-free application metrics and Prometheus text exposition.

Metric names use Prometheus's portable ``[A-Za-z_:][A-Za-z0-9_:]*`` form.
Metric and label names may not use Prometheus's reserved ``__`` prefix.
Label names otherwise use ``[A-Za-z_][A-Za-z0-9_]*``. Invalid names are
rejected instead of rewritten so distinct caller-supplied names cannot
silently collapse into one time series. Label values remain UTF-8 strings
and are escaped only when rendered.

Callers are responsible for using bounded-cardinality label values. In
particular, HTTP callers must use matched route templates rather than raw URL
paths containing user-controlled identifiers.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections import defaultdict
from itertools import pairwise
from typing import Any, TypedDict

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_METRIC_NAME_PATTERN = re.compile(r"[A-Za-z_:][A-Za-z0-9_:]*")
_LABEL_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_UPTIME_METRIC_NAME = "uptime_seconds"
_UPTIME_HELP = "Time elapsed since this metrics registry was created"
_NO_RESERVED_LABELS: frozenset[str] = frozenset()
_HISTOGRAM_RESERVED_LABELS = frozenset({"le"})

_LabelSet = tuple[tuple[str, str], ...]


class _ValueSample(TypedDict):
    name: str
    labels: dict[str, str]
    value: float


class _HistogramSample(TypedDict):
    name: str
    labels: dict[str, str]
    sum: float
    count: int
    buckets: dict[str, int]


def _validate_metric_name(name: str) -> None:
    if _METRIC_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(
            f"invalid Prometheus metric name {name!r}; expected [A-Za-z_:][A-Za-z0-9_:]*"
        )
    if name.startswith("__"):
        raise ValueError(f"invalid Prometheus metric name {name!r}; the '__' prefix is reserved")
    if name == _UPTIME_METRIC_NAME:
        raise ValueError(f"{_UPTIME_METRIC_NAME!r} is reserved for registry uptime")


def _label_key(
    labels: dict[str, str],
    *,
    reserved: frozenset[str] = _NO_RESERVED_LABELS,
) -> _LabelSet:
    for name, value in labels.items():
        if _LABEL_NAME_PATTERN.fullmatch(name) is None or name.startswith("__"):
            raise ValueError(
                f"invalid Prometheus label name {name!r}; expected "
                "[A-Za-z_][A-Za-z0-9_]* without the reserved '__' prefix"
            )
        if name in reserved:
            raise ValueError(f"label name {name!r} is reserved by this metric type")
        if not isinstance(value, str):
            raise TypeError(f"Prometheus label {name!r} must have a string value")
    return tuple(sorted(labels.items()))


def _escape_help(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def _format_help(name: str, value: str) -> str:
    escaped = _escape_help(value)
    return f"# HELP {name} {escaped}" if escaped else f"# HELP {name}"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(labels: _LabelSet, *, extra: _LabelSet = ()) -> str:
    pairs = (*labels, *extra)
    if not pairs:
        return ""
    rendered = ",".join(f'{name}="{_escape_label_value(value)}"' for name, value in pairs)
    return f"{{{rendered}}}"


def _format_number(value: float | int) -> str:
    numeric = float(value)
    if math.isnan(numeric):
        return "NaN"
    if math.isinf(numeric):
        return "+Inf" if numeric > 0 else "-Inf"
    return str(numeric) if isinstance(value, bool) else str(value)


class _Counter:
    """Thread-safe monotonic counter."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help = help_text
        self._values: dict[_LabelSet, float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, amount: float = 1, **labels: str) -> None:
        numeric_amount = float(amount)
        if not math.isfinite(numeric_amount) or numeric_amount < 0:
            raise ValueError("a Prometheus counter increment must be finite and non-negative")
        key = _label_key(labels)
        with self._lock:
            self._values[key] += numeric_amount

    def collect(self) -> list[_ValueSample]:
        with self._lock:
            return [
                {"name": self.name, "labels": dict(k), "value": v} for k, v in self._values.items()
            ]


class _Gauge:
    """Thread-safe gauge (can go up and down)."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help = help_text
        self._values: dict[_LabelSet, float] = defaultdict(float)
        self._lock = threading.Lock()

    def set(self, value: float, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            self._values[key] += amount

    def dec(self, amount: float = 1, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            self._values[key] -= amount

    def collect(self) -> list[_ValueSample]:
        with self._lock:
            return [
                {"name": self.name, "labels": dict(k), "value": v} for k, v in self._values.items()
            ]


class _Histogram:
    """Simple histogram with fixed buckets for request latencies."""

    _DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self, name: str, help_text: str, buckets: tuple[float, ...] | None = None) -> None:
        self.name = name
        self.help = help_text
        configured = buckets or self._DEFAULT_BUCKETS
        # Prometheus requires a terminal +Inf bucket so the largest bucket count
        # always equals the total observation count (le semantics). Append it if
        # the caller did not already supply one.
        finite = configured[:-1] if configured and configured[-1] == math.inf else configured
        if any(not math.isfinite(bucket) for bucket in finite):
            raise ValueError("Prometheus histogram buckets must be finite except for terminal +Inf")
        if any(upper <= lower for lower, upper in pairwise(finite)):
            raise ValueError("Prometheus histogram buckets must be strictly increasing")
        self.buckets = (*finite, math.inf)
        self._counts: dict[_LabelSet, list[int]] = {}
        self._sums: dict[_LabelSet, float] = defaultdict(float)
        self._totals: dict[_LabelSet, int] = defaultdict(int)
        self._lock = threading.Lock()

    def observe(self, value: float, **labels: str) -> None:
        if not math.isfinite(value):
            raise ValueError("Prometheus histogram observations must be finite")
        key = _label_key(labels, reserved=_HISTOGRAM_RESERVED_LABELS)
        with self._lock:
            if key not in self._counts:
                self._counts[key] = [0] * len(self.buckets)
            for i, b in enumerate(self.buckets):
                if value <= b:
                    self._counts[key][i] += 1
            self._sums[key] += value
            self._totals[key] += 1

    def collect(self) -> list[_HistogramSample]:
        with self._lock:
            results: list[_HistogramSample] = []
            for key in self._totals:
                results.append(
                    {
                        "name": self.name,
                        "labels": dict(key),
                        "sum": self._sums[key],
                        "count": self._totals[key],
                        "buckets": dict(
                            zip(
                                [_format_number(bucket) for bucket in self.buckets],
                                self._counts.get(key, [0] * len(self.buckets)),
                                strict=True,
                            )
                        ),
                    }
                )
            return results


class MetricsRegistry:
    """Central registry for JSON collection and Prometheus text exposition."""

    def __init__(self) -> None:
        self._metrics: dict[str, _Counter | _Gauge | _Histogram] = {}
        self._lock = threading.Lock()
        self._start_time = time.monotonic()

    def counter(self, name: str, help_text: str = "") -> _Counter:
        _validate_metric_name(name)
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                metric = _Counter(name, help_text)
                self._metrics[name] = metric
            elif not isinstance(metric, _Counter):
                raise ValueError(f"metric {name!r} is already registered with another type")
            return metric

    def gauge(self, name: str, help_text: str = "") -> _Gauge:
        _validate_metric_name(name)
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                metric = _Gauge(name, help_text)
                self._metrics[name] = metric
            elif not isinstance(metric, _Gauge):
                raise ValueError(f"metric {name!r} is already registered with another type")
            return metric

    def histogram(
        self, name: str, help_text: str = "", buckets: tuple[float, ...] | None = None
    ) -> _Histogram:
        _validate_metric_name(name)
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                metric = _Histogram(name, help_text, buckets)
                self._metrics[name] = metric
            elif not isinstance(metric, _Histogram):
                raise ValueError(f"metric {name!r} is already registered with another type")
            return metric

    def collect_all(self) -> dict[str, Any]:
        """Collect all metrics as a JSON-serializable dict."""
        result: dict[str, Any] = {"uptime_seconds": round(time.monotonic() - self._start_time, 1)}
        with self._lock:
            metrics = list(self._metrics.items())
        for name, metric in metrics:
            result[name] = metric.collect()
        return result

    def render_prometheus(self) -> str:
        """Render the registry in Prometheus text format 0.0.4.

        Metric families and label sets are sorted for reproducible output. Float
        special values use Prometheus's canonical ``NaN``, ``+Inf``, and
        ``-Inf`` spellings.
        """
        with self._lock:
            metrics = dict(self._metrics)

        lines: list[str] = []
        for name in sorted([*metrics, _UPTIME_METRIC_NAME]):
            if name == _UPTIME_METRIC_NAME:
                uptime = round(time.monotonic() - self._start_time, 1)
                lines.extend(
                    (
                        f"# HELP {name} {_UPTIME_HELP}",
                        f"# TYPE {name} gauge",
                        f"{name} {_format_number(uptime)}",
                    )
                )
                continue
            lines.extend(_render_metric(metrics[name]))
        return "\n".join(lines) + "\n"


def _render_metric(metric: _Counter | _Gauge | _Histogram) -> list[str]:
    if isinstance(metric, _Counter):
        metric_type = "counter"
    elif isinstance(metric, _Gauge):
        metric_type = "gauge"
    else:
        metric_type = "histogram"

    lines = [
        _format_help(metric.name, metric.help),
        f"# TYPE {metric.name} {metric_type}",
    ]
    if isinstance(metric, _Histogram):
        lines.extend(_render_histogram_samples(metric))
    else:
        lines.extend(_render_value_samples(metric))
    return lines


def _ordered_sample_labels(sample: _ValueSample | _HistogramSample) -> _LabelSet:
    # _label_key sorts once at ingestion; dict(_LabelSet) preserves that canonical order.
    return tuple(sample["labels"].items())


def _render_value_samples(metric: _Counter | _Gauge) -> list[str]:
    lines: list[str] = []
    for sample in sorted(metric.collect(), key=_ordered_sample_labels):
        labels = _ordered_sample_labels(sample)
        lines.append(f"{sample['name']}{_format_labels(labels)} {_format_number(sample['value'])}")
    return lines


def _render_histogram_samples(metric: _Histogram) -> list[str]:
    lines: list[str] = []
    for sample in sorted(metric.collect(), key=_ordered_sample_labels):
        labels = _ordered_sample_labels(sample)
        for upper_bound, count in sample["buckets"].items():
            bucket_labels = _format_labels(labels, extra=(("le", upper_bound),))
            lines.append(f"{sample['name']}_bucket{bucket_labels} {_format_number(count)}")
        plain_labels = _format_labels(labels)
        lines.append(f"{sample['name']}_sum{plain_labels} {_format_number(sample['sum'])}")
        lines.append(f"{sample['name']}_count{plain_labels} {_format_number(sample['count'])}")
    return lines


# Global metrics registry
registry = MetricsRegistry()

# Pre-defined application metrics
http_requests_total = registry.counter("http_requests_total", "Total HTTP requests")
http_request_duration = registry.histogram("http_request_duration_seconds", "HTTP request latency")
tasks_submitted_total = registry.counter("tasks_submitted_total", "Total tasks submitted")
tasks_completed_total = registry.counter("tasks_completed_total", "Total tasks completed")
tasks_failed_total = registry.counter("tasks_failed_total", "Total tasks failed")
active_tasks = registry.gauge("active_tasks", "Currently running tasks")
llm_requests_total = registry.counter("llm_requests_total", "Total LLM API calls")
llm_errors_total = registry.counter("llm_errors_total", "Total LLM API errors")
circuit_breaker_state = registry.gauge(
    "circuit_breaker_state", "Circuit breaker state (0=closed, 1=open, 2=half_open)"
)
sandbox_containers_active = registry.gauge("sandbox_containers_active", "Active sandbox containers")

# --- ADR-037 engine-core baseline -------------------------------------------
# These names are the taxonomy contract (docs/adr/ADR-037). Three of the six
# baseline metrics are live below; maistro_llm_tokens_total,
# maistro_llm_cost_usd_total, and maistro_quota_remaining_ratio still need
# their label provenance (model / service_key / period) plumbed to an emission
# seam — no current call site knows those values — and remain `gap-impl`
# under [engine-031].
maistro_request_duration_seconds = registry.histogram(
    "maistro_request_duration_seconds",
    "HTTP request latency in seconds (ADR-037; labels: route, outcome)",
)
maistro_security_block_total = registry.counter(
    "maistro_security_block_total",
    "Requests blocked at a security gate (ADR-037; labels: gate, reason)",
)
maistro_circuit_state = registry.gauge(
    "maistro_circuit_state",
    "Circuit state per dependency (ADR-037; 0=closed, 1=half-open, 2=open)",
)

# --- Recovery disposition (#462 / #338) --------------------------------------
# Refreshed by `Container.recover_abandoned_attempts`, the operator-scheduled
# recovery tick — the one place that already looks at the whole store. A
# non-terminal Run that keeps aging between ticks is the alarm these exist to
# ring: durable state claiming work is in flight that no process owns.
recovered_attempts_total = registry.counter(
    "maistro_recovered_attempts_total",
    "Attempts reclaimed from lapsed execution leases and reconciled (#462)",
)
non_terminal_runs = registry.gauge(
    "maistro_non_terminal_runs",
    "Runs currently in a non-terminal status, as of the last recovery tick",
)
oldest_non_terminal_run_age_seconds = registry.gauge(
    "maistro_oldest_non_terminal_run_age_seconds",
    "Age of the oldest non-terminal Run, as of the last recovery tick",
)
