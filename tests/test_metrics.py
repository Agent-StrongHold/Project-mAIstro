"""Tests for observability metrics."""

from __future__ import annotations

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


def test_collect_all():
    reg = MetricsRegistry()
    c = reg.counter("requests", "total requests")
    c.inc()
    result = reg.collect_all()
    assert "uptime_seconds" in result
    assert "requests" in result
