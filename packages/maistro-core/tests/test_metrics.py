"""Tests for observability metrics."""

from __future__ import annotations

import pytest

from maistro.observability.metrics import MetricsRegistry


def test_counter_increment():
    reg = MetricsRegistry()
    c = reg.counter("test_total", "test counter")
    c.inc()
    c.inc(amount=5)
    collected = c.collect()
    assert len(collected) == 1
    assert collected[0]["value"] == 6


def test_counter_with_labels():
    reg = MetricsRegistry()
    c = reg.counter("test_labeled", "test")
    c.inc(method="GET")
    c.inc(method="POST")
    c.inc(method="GET")
    collected = c.collect()
    assert len(collected) == 2
    values = {tuple(sorted(d["labels"].items())): d["value"] for d in collected}
    assert values[(("method", "GET"),)] == 2
    assert values[(("method", "POST"),)] == 1


def test_gauge_set_and_inc():
    reg = MetricsRegistry()
    g = reg.gauge("active", "test gauge")
    g.set(10)
    g.inc(5)
    g.dec(3)
    collected = g.collect()
    assert collected[0]["value"] == 12


def test_histogram_observe():
    reg = MetricsRegistry()
    h = reg.histogram("latency", "test")
    h.observe(0.05)
    h.observe(0.5)
    h.observe(2.0)
    collected = h.collect()
    assert len(collected) == 1
    assert collected[0]["count"] == 3
    assert collected[0]["sum"] == 2.55


def test_histogram_has_inf_bucket_for_large_observations():
    """Observations larger than the largest finite bucket must still be counted.

    Prometheus requires a +Inf bucket so that the terminal bucket count equals
    the total observation count. Without it, large observations increment the
    sum and total but no bucket, corrupting upper-tail quantiles.
    """
    reg = MetricsRegistry()
    h = reg.histogram("latency", "test")  # uses default buckets (max finite = 10.0)
    h.observe(42.0)  # larger than every finite bucket
    collected = h.collect()
    assert len(collected) == 1
    entry = collected[0]
    assert entry["count"] == 1
    # There must be a +Inf bucket and it must count the large observation.
    assert "+Inf" in entry["buckets"]
    assert entry["buckets"]["+Inf"] == 1


def test_histogram_terminal_bucket_equals_total_count():
    """Prometheus invariant: the +Inf (terminal) bucket count == total count.

    Buckets are cumulative (le semantics), so the largest bucket must include
    every observation regardless of magnitude.
    """
    reg = MetricsRegistry()
    h = reg.histogram("latency", "test")
    for v in (0.001, 0.05, 0.5, 2.0, 9.9, 11.0, 100.0):
        h.observe(v)
    entry = h.collect()[0]
    assert entry["count"] == 7
    # Terminal (+Inf) bucket is cumulative and must equal the total count.
    assert entry["buckets"]["+Inf"] == entry["count"]
    # Cumulative buckets are monotonically non-decreasing and capped at count.
    finite_counts = [entry["buckets"][b] for b in entry["buckets"] if b != "+Inf"]
    assert finite_counts == sorted(finite_counts)
    assert all(c <= entry["count"] for c in finite_counts)


def test_collect_all():
    reg = MetricsRegistry()
    c = reg.counter("requests", "total requests")
    c.inc()
    result = reg.collect_all()
    assert "uptime_seconds" in result
    assert "requests" in result


@pytest.mark.ac("SPEC-228/AC-2")
def test_reregistering_a_name_returns_the_same_instrument():
    """Two callers asking for one metric must share it, not shadow each other.

    Modules register their metrics at import time, so the same name is reached
    from several places. If the second call replaced the first instrument, the
    counts already recorded through the first handle would silently stop being
    collected — a metric that reads zero while the code paths under it run.
    """
    reg = MetricsRegistry()
    first = reg.counter("shared_total", "first")
    first.inc(amount=3)
    second = reg.counter("shared_total", "second")

    assert second is first
    assert second.collect()[0]["value"] == 3

    assert reg.gauge("g", "") is reg.gauge("g", "")
    assert reg.histogram("h", "") is reg.histogram("h", "")


@pytest.mark.ac("SPEC-228/AC-2")
def test_registry_exposes_all_three_instrument_kinds():
    reg = MetricsRegistry()
    reg.counter("c", "").inc()
    reg.gauge("g", "").set(2)
    reg.histogram("h", "").observe(0.5)

    collected = reg.collect_all()
    assert {"c", "g", "h"} <= set(collected)
