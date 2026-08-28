"""Prometheus-style application metrics.

Lightweight in-process counters and gauges exposed via /metrics endpoint.
No external dependency — uses a simple registry so Prometheus can scrape.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any


class _Counter:
    """Thread-safe monotonic counter."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help = help_text
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, amount: float = 1, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] += amount

    def collect(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"name": self.name, "labels": dict(k), "value": v} for k, v in self._values.items()
            ]


class _Gauge:
    """Thread-safe gauge (can go up and down)."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help = help_text
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def set(self, value: float, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] += amount

    def dec(self, amount: float = 1, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] -= amount

    def collect(self) -> list[dict[str, Any]]:
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
        finite = buckets or self._DEFAULT_BUCKETS
        # Prometheus requires a terminal +Inf bucket so the largest bucket count
        # always equals the total observation count (le semantics). Append it if
        # the caller did not already supply one.
        if not finite or finite[-1] != float("inf"):
            finite = (*finite, float("inf"))
        self.buckets = finite
        self._counts: dict[tuple[tuple[str, str], ...], list[int]] = {}
        self._sums: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._totals: dict[tuple[tuple[str, str], ...], int] = defaultdict(int)
        self._lock = threading.Lock()

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            if key not in self._counts:
                self._counts[key] = [0] * len(self.buckets)
            for i, b in enumerate(self.buckets):
                if value <= b:
                    self._counts[key][i] += 1
            self._sums[key] += value
            self._totals[key] += 1

    def collect(self) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for key in self._totals:
                results.append(
                    {
                        "name": self.name,
                        "labels": dict(key),
                        "sum": self._sums[key],
                        "count": self._totals[key],
                        "buckets": dict(
                            zip(
                                ["+Inf" if b == float("inf") else str(b) for b in self.buckets],
                                self._counts.get(key, [0] * len(self.buckets)),
                                strict=True,
                            )
                        ),
                    }
                )
            return results


class MetricsRegistry:
    """Central registry for all application metrics."""

    def __init__(self) -> None:
        self._metrics: dict[str, _Counter | _Gauge | _Histogram] = {}
        self._start_time = time.monotonic()

    def counter(self, name: str, help_text: str = "") -> _Counter:
        if name not in self._metrics:
            self._metrics[name] = _Counter(name, help_text)
        return self._metrics[name]  # type: ignore[return-value]

    def gauge(self, name: str, help_text: str = "") -> _Gauge:
        if name not in self._metrics:
            self._metrics[name] = _Gauge(name, help_text)
        return self._metrics[name]  # type: ignore[return-value]

    def histogram(
        self, name: str, help_text: str = "", buckets: tuple[float, ...] | None = None
    ) -> _Histogram:
        if name not in self._metrics:
            self._metrics[name] = _Histogram(name, help_text, buckets)
        return self._metrics[name]  # type: ignore[return-value]

    def collect_all(self) -> dict[str, Any]:
        """Collect all metrics as a JSON-serializable dict."""
        result: dict[str, Any] = {"uptime_seconds": round(time.monotonic() - self._start_time, 1)}
        for name, metric in self._metrics.items():
            result[name] = metric.collect()
        return result


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


# --- Recoverable non-terminal Runs (#338) ------------------------------------
# Current state, deliberately not a running total. `stranded_chat_runs_total`
# counts compensation writes that failed, cumulatively, inside one process: it
# reads zero in a process that just started on a database full of stranded rows,
# and it never falls when they are settled. These are derived from the store, so
# they answer "is anything stranded right now, and how long has it been" and
# return to zero once the last non-terminal Run terminalizes.
non_terminal_runs = registry.gauge(
    "maistro_non_terminal_runs",
    "Runs in a non-terminal status as of the last recovery tick (#338)",
)
oldest_non_terminal_run_age_seconds = registry.gauge(
    "maistro_oldest_non_terminal_run_age_seconds",
    "Age of the oldest non-terminal Run as of the last recovery tick (#338)",
)
