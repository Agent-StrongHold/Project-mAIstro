"""Dependency-free application metrics and Prometheus text exposition.

Metric names use Prometheus's portable ``[A-Za-z_:][A-Za-z0-9_:]*`` form.
Metric and label names may not use Prometheus's reserved ``__`` prefix.
Label names otherwise use ``[A-Za-z_][A-Za-z0-9_]*``. Invalid names are
rejected instead of rewritten so distinct caller-supplied names cannot
silently collapse into one time series. Label values remain UTF-8 strings
and are escaped only when rendered.

Callers are responsible for using bounded-cardinality label values. In
particular, HTTP callers must use matched route templates rather than raw URL
paths containing user-controlled identifiers. Because one missed caller must
not turn that responsibility into unbounded process-memory growth, the
registry additionally caps the number of distinct label sets a metric may
hold (#818 AC-3): past the cap, new label sets are dropped and counted in
``metrics_series_overflow_total`` instead of stored.

The same failure shape exists one level up: a caller minting metric *names*
from unbounded input would otherwise grow the registry family by family. The
registry therefore also caps how many distinct caller-requested metric
families it will hold; past that cap, registrations of brand-new names return
a dropping sink (same interface, writes are no-ops) and the refusal is
counted in ``metrics_registry_overflow_total``. Both caps are memory
backstops, not quotas — legitimate instrumentation stays far below them.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import pairwise
from typing import Any, Literal, Protocol, TypedDict, TypeVar

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_METRIC_NAME_PATTERN = re.compile(r"[A-Za-z_:][A-Za-z0-9_:]*")
_LABEL_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_UPTIME_METRIC_NAME = "uptime_seconds"
_UPTIME_HELP = "Time elapsed since this metrics registry was created"
_NO_RESERVED_LABELS: frozenset[str] = frozenset()
_HISTOGRAM_RESERVED_LABELS = frozenset({"le"})

#: Default per-metric cap on distinct label sets (series). Route-template
#: labels keep well under this by construction; the cap is a backstop for a
#: caller that missed that memo, not a quota anyone should plan against.
DEFAULT_MAX_SERIES_PER_METRIC = 10_000

#: Overflow signal counter, created lazily on the first dropped sample so
#: clean registries keep rendering only what exists (#818 AC-3).
_OVERFLOW_METRIC_NAME = "metrics_series_overflow_total"
_OVERFLOW_METRIC_HELP = (
    "Samples dropped because their metric reached its series-cardinality cap (#818)"
)

#: Family-cap signal counter, created lazily on the first refused metric
#: registration. Unlabeled by construction: a caller-controlled label here
#: would reintroduce exactly the unbounded growth the family cap exists to
#: stop.
_REGISTRY_OVERFLOW_METRIC_NAME = "metrics_registry_overflow_total"
_REGISTRY_OVERFLOW_METRIC_HELP = (
    "Metric-family registrations refused because the registry reached its family cap"
)

_LabelSet = tuple[tuple[str, str], ...]


class _SeriesCap:
    """Backstop bounding a metric's distinct label sets (#818 AC-3).

    Route-template labels keep cardinality small by construction, but the
    registry must also survive one caller that feeds request-controlled text
    into a label: once the metric already holds ``max_series`` label sets,
    further *new* sets are dropped and reported through ``on_overflow``
    instead of stored. Existing series keep updating, so a cap hit degrades
    resolution — never correctness — and memory stays bounded no matter what
    a caller does.
    """

    __slots__ = ("max_series", "on_overflow")

    def __init__(self, max_series: int | None, on_overflow: Callable[[str], None] | None) -> None:
        self.max_series = max_series
        self.on_overflow = on_overflow

    def admits(self, values: dict[_LabelSet, Any], key: _LabelSet, metric_name: str) -> bool:
        """Whether ``key`` may be stored. Callers must hold the metric's lock
        so this membership test and the insertion it authorizes are atomic."""
        if self.max_series is None or key in values or len(values) < self.max_series:
            return True
        if self.on_overflow is not None:
            self.on_overflow(metric_name)
        return False


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
    if name in (_OVERFLOW_METRIC_NAME, _REGISTRY_OVERFLOW_METRIC_NAME):
        raise ValueError(f"{name!r} is reserved for registry overflow accounting")


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

    def __init__(self, name: str, help_text: str, *, series_cap: _SeriesCap | None = None) -> None:
        self.name = name
        self.help = help_text
        self._values: dict[_LabelSet, float] = defaultdict(float)
        self._lock = threading.Lock()
        self._series_cap = series_cap if series_cap is not None else _SeriesCap(None, None)

    def inc(self, amount: float = 1, **labels: str) -> None:
        numeric_amount = float(amount)
        if not math.isfinite(numeric_amount) or numeric_amount < 0:
            raise ValueError("a Prometheus counter increment must be finite and non-negative")
        key = _label_key(labels)
        with self._lock:
            if not self._series_cap.admits(self._values, key, self.name):
                return
            self._values[key] += numeric_amount

    def collect(self) -> list[_ValueSample]:
        with self._lock:
            return [
                {"name": self.name, "labels": dict(k), "value": v} for k, v in self._values.items()
            ]


class _Gauge:
    """Thread-safe gauge (can go up and down)."""

    def __init__(self, name: str, help_text: str, *, series_cap: _SeriesCap | None = None) -> None:
        self.name = name
        self.help = help_text
        self._values: dict[_LabelSet, float] = defaultdict(float)
        self._lock = threading.Lock()
        self._series_cap = series_cap if series_cap is not None else _SeriesCap(None, None)

    def set(self, value: float, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            if not self._series_cap.admits(self._values, key, self.name):
                return
            self._values[key] = value

    def inc(self, amount: float = 1, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            if not self._series_cap.admits(self._values, key, self.name):
                return
            self._values[key] += amount

    def dec(self, amount: float = 1, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            if not self._series_cap.admits(self._values, key, self.name):
                return
            self._values[key] -= amount

    def remove(self, **labels: str) -> None:
        """Drop a labeled series entirely, so a condition that no longer holds
        stops reporting instead of reporting its last value forever. A gauge
        whose subject disappeared (a table drained to empty, a measurement a
        backend cannot take) must publish nothing — a stale value is a
        fabricated health signal (#325 retention health)."""
        key = _label_key(labels)
        with self._lock:
            self._values.pop(key, None)

    def collect(self) -> list[_ValueSample]:
        with self._lock:
            return [
                {"name": self.name, "labels": dict(k), "value": v} for k, v in self._values.items()
            ]


class _Histogram:
    """Simple histogram with fixed buckets for request latencies."""

    _DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(
        self,
        name: str,
        help_text: str,
        buckets: tuple[float, ...] | None = None,
        *,
        series_cap: _SeriesCap | None = None,
    ) -> None:
        self.name = name
        self.help = help_text
        self._series_cap = series_cap if series_cap is not None else _SeriesCap(None, None)
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
            if not self._series_cap.admits(self._totals, key, self.name):
                return
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


#: Default cap on distinct metric families a registry will hold. The
#: predefined application metrics number in the dozens; this backstop fires
#: only for a caller minting metric names from unbounded input (ids, paths,
#: tenants) — the same failure shape as the per-metric series cap, one level
#: up. Backstop accounting counters (the two overflow metrics) are exempt.
DEFAULT_MAX_METRICS_PER_REGISTRY = 1_000

_MetricT = TypeVar("_MetricT", _Counter, _Gauge, _Histogram)


class MetricsRegistry:
    """Central registry for JSON collection and Prometheus text exposition.

    Every metric the registry creates carries the same series-cardinality
    backstop (#818 AC-3): past ``max_series_per_metric`` distinct label sets,
    new sets are dropped and counted in ``metrics_series_overflow_total``
    rather than stored, so a caller with unbounded label values cannot grow
    process memory without bound.

    The backstop also covers unbounded metric *families*: past
    ``max_metrics_per_registry`` distinct caller-requested names, registering
    a brand-new metric returns a dropping sink (same interface, writes are
    no-ops) and the refusal is counted in the unlabeled
    ``metrics_registry_overflow_total``. The two overflow counters are exempt
    from the family cap, so registry memory is bounded at
    ``max_metrics_per_registry`` families plus fixed-size accounting.
    """

    def __init__(
        self,
        max_series_per_metric: int | None = None,
        max_metrics_per_registry: int | None = None,
    ) -> None:
        # None keeps the optional configuration API while retaining the safe
        # default; there is no public uncapped mode because this is a backstop.
        cap = (
            DEFAULT_MAX_SERIES_PER_METRIC
            if max_series_per_metric is None
            else max_series_per_metric
        )
        if cap is not None and cap < 1:
            raise ValueError("max_series_per_metric must be at least 1 when set")
        family_cap = (
            DEFAULT_MAX_METRICS_PER_REGISTRY
            if max_metrics_per_registry is None
            else max_metrics_per_registry
        )
        if family_cap < 1:
            raise ValueError("max_metrics_per_registry must be at least 1 when set")
        self._metrics: dict[str, _Counter | _Gauge | _Histogram] = {}
        self._lock = threading.Lock()
        self._start_time = time.monotonic()
        self._series_cap = _SeriesCap(cap, self._record_overflow)
        self._family_cap = family_cap
        # Caller-requested families actually stored; the exempt overflow
        # counters are not counted against the family cap.
        self._caller_families = 0

    def _record_overflow(self, metric_name: str) -> None:
        """Count one dropped sample; never raises into the guarded metric.

        Called with the reporting metric's lock held, so it must not touch that
        metric again — only the lazily created overflow counter. That counter
        is itself series-capped (with no recursion wiring): dynamic metric
        names are exactly the unbounded input this module defends against, so
        its ``metric`` label space must not inherit them without bound. Once
        the overflow counter is at its cap, records for further new metric
        names are dropped — resolution loss, never unbounded memory.
        """
        try:
            with self._lock:
                overflow = self._metrics.get(_OVERFLOW_METRIC_NAME)
                if overflow is None:
                    overflow = _Counter(
                        _OVERFLOW_METRIC_NAME,
                        _OVERFLOW_METRIC_HELP,
                        series_cap=_SeriesCap(self._series_cap.max_series, None),
                    )
                    self._metrics[_OVERFLOW_METRIC_NAME] = overflow
                elif not isinstance(overflow, _Counter):
                    return
            overflow.inc(metric=metric_name)
        except Exception:
            pass  # a backstop that breaks the metric it guards guards nothing

    def _refuse_family(self, sink: _MetricT) -> _MetricT:
        """Handle a brand-new metric past the family cap: count the refusal
        (lazily creating the exempt, unlabeled accounting counter) and return
        a dropping sink so the caller keeps a working instrument. Callers must
        hold the registry lock; ``sink`` is deliberately not stored.
        """
        overflow = self._metrics.get(_REGISTRY_OVERFLOW_METRIC_NAME)
        if overflow is None:
            overflow = _Counter(_REGISTRY_OVERFLOW_METRIC_NAME, _REGISTRY_OVERFLOW_METRIC_HELP)
            self._metrics[_REGISTRY_OVERFLOW_METRIC_NAME] = overflow
        if isinstance(overflow, _Counter):
            # Unlabeled and single-series by construction, so this cannot grow.
            overflow.inc()
        return sink

    def counter(self, name: str, help_text: str = "") -> _Counter:
        _validate_metric_name(name)
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                if self._caller_families >= self._family_cap:
                    return self._refuse_family(
                        _Counter(name, help_text, series_cap=_SeriesCap(0, None))
                    )
                metric = _Counter(name, help_text, series_cap=self._series_cap)
                self._metrics[name] = metric
                self._caller_families += 1
            elif not isinstance(metric, _Counter):
                raise ValueError(f"metric {name!r} is already registered with another type")
            return metric

    def gauge(self, name: str, help_text: str = "") -> _Gauge:
        _validate_metric_name(name)
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                if self._caller_families >= self._family_cap:
                    return self._refuse_family(
                        _Gauge(name, help_text, series_cap=_SeriesCap(0, None))
                    )
                metric = _Gauge(name, help_text, series_cap=self._series_cap)
                self._metrics[name] = metric
                self._caller_families += 1
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
                if self._caller_families >= self._family_cap:
                    return self._refuse_family(
                        _Histogram(name, help_text, buckets, series_cap=_SeriesCap(0, None))
                    )
                metric = _Histogram(name, help_text, buckets, series_cap=self._series_cap)
                self._metrics[name] = metric
                self._caller_families += 1
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
maistro_security_advisory_degraded_total = registry.counter(
    "maistro_security_advisory_degraded_total",
    "Advisory security layer unavailable, gate proceeded under its documented "
    "degraded policy (#1191; labels: gate) — an availability alarm, not a block",
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

# --- Retention (#1175) --------------------------------------------------------
# Emitted by `RunRetentionSweeper` after each completed sweep. The label is
# the sweep's authorization mode, never a Workspace id: Workspaces are
# caller-created, and metric label values are bounded (#818). What was
# deleted per class of dependent evidence rides on the sweep's `PurgeOutcome`,
# whose per-sweep shape carries the scope id and the
# dependent counts a counter label could not hold bounded.
retention_purged_total = registry.counter(
    "maistro_retention_purged_total",
    "Runs deleted by retention sweeps, by authorization mode (workspace|global) (#1175)",
)
retention_backlog_remaining = registry.gauge(
    "maistro_retention_backlog_remaining",
    "Retention scopes whose last completed sweep hit its batch limit before the "
    "scope drained; by authorization mode (#1175)",
)
retention_backlog_age_seconds = registry.gauge(
    "maistro_retention_backlog_age_seconds",
    "Age in seconds of the oldest scope still counted by "
    "maistro_retention_backlog_remaining, by authorization mode; 0 when no scope "
    "is backlogged (#1175)",
)
retention_sweep_last_success_timestamp = registry.gauge(
    "maistro_retention_sweep_last_success_timestamp",
    "Unix timestamp of the last retention sweep that completed and committed, "
    "by authorization mode; a failed sweep never advances it",
)
retention_sweep_failures_total = registry.counter(
    "maistro_retention_sweep_failures_total",
    "Retention sweeps that failed before committing anything, by authorization mode",
)
retention_table_rows = registry.gauge(
    "maistro_retention_table_rows",
    "Rows currently stored in a governed durable table, as of the last health "
    "probe that table's purge drove (#325; labels: table, backend) — a level, "
    "so a table that grows despite its policy is visible before its backlog age",
)
retention_table_bytes = registry.gauge(
    "maistro_retention_table_bytes",
    "Approximate stored size of a governed durable table (#325; labels: table, "
    "backend). PostgreSQL reports pg_total_relation_size; SQLite reports the "
    "dbstat page sum, and the series is simply absent where the runtime SQLite "
    "has no dbstat — no per-table byte count exists there without it",
)
retention_oldest_record_timestamp = registry.gauge(
    "maistro_retention_oldest_record_timestamp",
    "Unix timestamp of the oldest record still retained in a governed durable "
    "table, as of the last health probe (#325; labels: table, backend); absent "
    "while the table is empty — how far back the kept history actually reaches",
)

# --- Retention stored-volume health (#325) -----------------------------------
# The purge counters above are rates, and a rate cannot show the failure that
# matters most: a table whose purge never runs deletes nothing, publishes no
# purged count, and looks exactly as healthy as a table at steady state. What
# exposes that is a level — rows, bytes, and how far back the oldest retained
# record reaches, per governed table. Every driven purge is the probe's
# driver: after a purge commits, the store samples its own governed tables
# and publishes here. There is no scheduler in this repository to hang a
# scanner on (see `maistro.runs.retention`), and the purges are the one code
# path that already holds each store's connection on a cadence. The throttle
# is what makes that affordable, and honesty about what a backend cannot
# measure is what makes it trustworthy: an empty table publishes no
# oldest-record series, and SQLite without the dbstat runtime publishes no
# per-table bytes — an absent series, never a fabricated number.


#: How old a record's stored time representation may be parsed from. ISO-8601
#: text orders the same way the datetimes do, which is why `MIN()` over a
#: payload timestamp needs no materialization (the same trick the recovery
#: tick's `non_terminal_run_stats` uses).
OldestUnit = Literal["iso", "unix_s", "unix_us", "datetime"]

#: The durable tables whose purge mechanisms this engine ships, and therefore
#: the bounded `table` label set (#818). Mirrors the `deletion_path` rows of
#: `quality/durable-table-retention.json`, which the CI inventory gate checks
#: against migrations.
_KNOWN_TABLES: frozenset[str] = frozenset(
    {
        "audit_log",
        "canonical_attempts",
        "canonical_event_log",
        "canonical_node_runs",
        "canonical_run_eval_scores",
        "canonical_runs",
        "graph_continuations",
        "security_rate_limits",
        "security_violations",
        "session_turns",
        "sessions",
        "task_idempotency",
        "usage_event_aggregates",
        "usage_events",
    }
)

#: Default minimum spacing between two probes of one store. Well under the
#: run-spine sweep interval (300s), so a swept store can publish every sweep,
#: while the inline purges (sessions on append, claims on admission) cost one
#: probe a minute at most.
DEFAULT_PROBE_INTERVAL_S = 60.0

#: Per store key — one process-wide entry per store that probes, not per scope
#: or per caller, by the same reasoning as `_BACKLOGGED_SCOPES` in
#: `maistro.runs.retention`: per-caller throttles do not compose.
_LAST_PROBE: dict[str, float] = {}
_PROBE_LOCK = threading.Lock()


@dataclass(frozen=True)
class RetentionTableSample:
    """One governed table's stored volume, as observed by its purge's probe."""

    #: The inventory's table name — a bounded label, checked against
    #: `_KNOWN_TABLES` before anything is published.
    table: str
    rows: int
    #: `None` where the backend cannot measure it (SQLite without dbstat).
    total_bytes: int | None = None
    #: Unix timestamp of the oldest retained record; `None` for an empty
    #: table (an absent series, not a fabricated zero) or where the stored
    #: time could not be parsed.
    oldest_timestamp: float | None = None


def oldest_timestamp(value: Any, unit: OldestUnit) -> float | None:
    """Convert a stored record time to a Unix timestamp, or `None`.

    Parse failures degrade to `None` rather than raising: a probe that cannot
    understand one stored format must not fail the purge that drove it, and an
    absent oldest-record series is the honest report of "unparseable".
    """
    if value is None:
        return None
    try:
        if unit == "iso":
            return datetime.fromisoformat(str(value)).timestamp()
        if unit == "unix_s":
            return float(value)
        if unit == "unix_us":
            return float(value) / 1_000_000
        if unit == "datetime":
            assert isinstance(value, datetime)  # nosec B101 - narrowing the typed union
            return value.timestamp()
    except (TypeError, ValueError):
        return None
    raise ValueError(f"unknown oldest-record unit: {unit}")  # pragma: no cover - caller bug


def retention_health_probe_due(
    key: str, *, min_interval_s: float = DEFAULT_PROBE_INTERVAL_S
) -> bool:
    """Whether (and stamp that) this store's probe may run now.

    Drivers consult this BEFORE sampling — the table scans are the cost being
    amortized, so gating only the gauge writes would throttle nothing. A
    `True` return has already stamped the ledger; the caller samples and then
    publishes with `min_interval_s=0` so the write is not re-throttled.
    """
    now = time.monotonic()
    with _PROBE_LOCK:
        last = _LAST_PROBE.get(key)
        if last is not None and (now - last) < min_interval_s:
            return False
        _LAST_PROBE[key] = now
        return True


def publish_retention_table_health(
    key: str,
    backend: str,
    samples: Sequence[RetentionTableSample],
    *,
    min_interval_s: float = DEFAULT_PROBE_INTERVAL_S,
) -> bool:
    """Publish one store's table samples, at most once per interval per key.

    Returns whether the samples were published; a throttled call publishes
    nothing and reports `False`. Stores that gate their sampling with
    :func:`retention_health_probe_due` pass `min_interval_s=0` here — the
    throttle has already been applied where it matters, before the samples
    were queried.
    """
    if not retention_health_probe_due(key, min_interval_s=min_interval_s):
        return False
    for sample in samples:
        if sample.table not in _KNOWN_TABLES:
            raise ValueError(
                f"retention health probe: {sample.table!r} is not a governed "
                "durable table; metric labels are bounded (#818)"
            )
        retention_table_rows.set(float(sample.rows), table=sample.table, backend=backend)
        if sample.total_bytes is not None:
            retention_table_bytes.set(
                float(sample.total_bytes), table=sample.table, backend=backend
            )
        else:
            # A measurement this probe could not take must not leave the
            # previous value standing in for it.
            retention_table_bytes.remove(table=sample.table, backend=backend)
        if sample.oldest_timestamp is not None:
            retention_oldest_record_timestamp.set(
                sample.oldest_timestamp, table=sample.table, backend=backend
            )
        else:
            # An empty table holds no oldest record; a stale timestamp would
            # claim history that is no longer there.
            retention_oldest_record_timestamp.remove(table=sample.table, backend=backend)
    return True


class PostgresFetchRow(Protocol):
    """The one asyncpg method the probe needs (`Connection.fetchrow`)."""

    def __call__(self, query: str, *args: object) -> Awaitable[Any]: ...


async def postgres_table_sample(
    fetchrow: PostgresFetchRow,
    table: str,
    oldest_expr: str,
    *,
    oldest_unit: OldestUnit,
) -> RetentionTableSample | None:
    """Sample one PostgreSQL table: rows, `pg_total_relation_size`, oldest record.

    Both interpolated identifiers are literals from this module and its
    callers' constants — the table name is checked against the whitelist
    first, and `oldest_expr` is a source-code constant per table (a payload
    `json_extract` or a plain column), never caller input. A table the
    deployment has not provisioned (an optional module's table) yields `None`
    rather than a zeroed sample, so nothing pretends an absent table is an
    empty one.
    """
    if table not in _KNOWN_TABLES:
        raise ValueError(f"retention health probe: unknown table {table!r}")
    if not await fetchrow("SELECT to_regclass($1) IS NOT NULL AS ok", table):
        return None
    row = await fetchrow(
        # nosec B608 - identifiers are whitelist-checked / source constants, values bound
        f"SELECT COUNT(*) AS n, MIN({oldest_expr}) AS oldest FROM {table}",
    )
    if row is None:  # pragma: no cover - COUNT always yields a row
        return None
    bytes_row = await fetchrow("SELECT pg_total_relation_size($1::regclass) AS b", table)
    return RetentionTableSample(
        table=table,
        rows=int(row["n"]),
        total_bytes=int(bytes_row["b"]) if bytes_row is not None else None,
        oldest_timestamp=oldest_timestamp(row["oldest"], oldest_unit),
    )


async def sqlite_table_sample(
    conn: Any,
    table: str,
    oldest_expr: str,
    *,
    oldest_unit: OldestUnit,
) -> RetentionTableSample | None:
    """Sample one SQLite table: rows, oldest record, and dbstat bytes if offered.

    `conn` is an `aiosqlite.Connection`, typed loosely here so this module
    does not import the driver for one annotation. A table that does not
    exist (an optional module's table sharing the database file) yields
    `None`; so does a runtime without dbstat, which is why the bytes series
    is documented as conditionally present on SQLite.
    """
    if table not in _KNOWN_TABLES:
        raise ValueError(f"retention health probe: unknown table {table!r}")
    try:
        async with conn.execute(
            # nosec B608 - identifiers are whitelist-checked / source constants
            f"SELECT COUNT(*) AS n, MIN({oldest_expr}) AS oldest FROM {table}",
        ) as cursor:
            row = await cursor.fetchone()
    except Exception as exc:
        if "no such table" in str(exc):
            return None
        raise
    if row is None:  # pragma: no cover - COUNT always yields a row
        return None
    sample = RetentionTableSample(
        table=table,
        rows=int(row[0]),
        total_bytes=None,
        oldest_timestamp=oldest_timestamp(row[1], oldest_unit),
    )
    bytes_sum = await sqlite_table_bytes(conn, table)
    if bytes_sum is not None:
        sample = replace(sample, total_bytes=bytes_sum)
    return sample


async def sqlite_table_bytes(conn: Any, table: str) -> int | None:
    """Per-table stored bytes via the dbstat virtual table, or `None`.

    dbstat ships in many but not all SQLite builds; a runtime without it gets
    no bytes series rather than a database-file-size stand-in that would
    overstate every table by the whole rest of the database.
    """
    if table not in _KNOWN_TABLES:
        raise ValueError(f"retention health probe: unknown table {table!r}")
    try:
        async with conn.execute(
            "SELECT SUM(pgsize) FROM dbstat WHERE name = ?", (table,)
        ) as cursor:
            row = await cursor.fetchone()
    except Exception as exc:
        if "no such table" in str(exc):
            return None
        raise
    if row is None or row[0] is None:
        return None
    return int(row[0])


__all__ = [
    "DEFAULT_PROBE_INTERVAL_S",
    "OldestUnit",
    "PostgresFetchRow",
    "RetentionTableSample",
    "oldest_timestamp",
    "postgres_table_sample",
    "publish_retention_table_health",
    "retention_health_probe_due",
    "sqlite_table_bytes",
    "sqlite_table_sample",
]
