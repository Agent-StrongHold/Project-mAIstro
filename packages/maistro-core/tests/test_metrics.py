"""Tests for observability metrics."""

from __future__ import annotations

import pytest

from maistro.observability import metrics as metrics_module
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


def test_prometheus_exposition_renders_all_instrument_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics_module.time, "monotonic", lambda: 100.0)
    reg = MetricsRegistry()
    reg.counter("requests_total", "Total requests").inc(amount=2, method="GET")
    reg.gauge("active_jobs", "Active jobs").set(3)
    histogram = reg.histogram("latency_seconds", "Request latency", buckets=(1.0, 2.0))
    for value in (0.5, 1.5, 3.0):
        histogram.observe(value, route="/items/{item_id}")

    assert reg.render_prometheus() == (
        "# HELP active_jobs Active jobs\n"
        "# TYPE active_jobs gauge\n"
        "active_jobs 3\n"
        "# HELP latency_seconds Request latency\n"
        "# TYPE latency_seconds histogram\n"
        'latency_seconds_bucket{route="/items/{item_id}",le="1.0"} 1\n'
        'latency_seconds_bucket{route="/items/{item_id}",le="2.0"} 2\n'
        'latency_seconds_bucket{route="/items/{item_id}",le="+Inf"} 3\n'
        'latency_seconds_sum{route="/items/{item_id}"} 5.0\n'
        'latency_seconds_count{route="/items/{item_id}"} 3\n'
        "# HELP requests_total Total requests\n"
        "# TYPE requests_total counter\n"
        'requests_total{method="GET"} 2.0\n'
        "# HELP uptime_seconds Time elapsed since this metrics registry was created\n"
        "# TYPE uptime_seconds gauge\n"
        "uptime_seconds 0.0\n"
    )


def test_prometheus_exposition_escapes_help_and_label_values() -> None:
    reg = MetricsRegistry()
    counter = reg.counter("escaped_total", "A backslash: \\ and a\nnew line")
    counter.inc(
        **{
            "detail": 'quote " backslash \\ newline\nnext line',
        }
    )

    rendered = reg.render_prometheus()

    assert "# HELP escaped_total A backslash: \\\\ and a\\nnew line\n" in rendered
    assert 'escaped_total{detail="quote \\" backslash \\\\ newline\\nnext line"} 1.0\n' in rendered


def test_prometheus_exposition_is_deterministically_sorted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics_module.time, "monotonic", lambda: 25.0)
    reg = MetricsRegistry()
    counter = reg.counter("z_total", "z")
    counter.inc(region="west", method="POST")
    counter.inc(region="east", method="GET")
    reg.gauge("a_value", "a").set(1)

    first = reg.render_prometheus()
    second = reg.render_prometheus()

    assert first == second
    assert first.index("# HELP a_value") < first.index("# HELP uptime_seconds")
    assert first.index("# HELP uptime_seconds") < first.index("# HELP z_total")
    assert first.index('method="GET",region="east"') < first.index('method="POST",region="west"')


def test_prometheus_name_policy_rejects_invalid_and_reserved_names() -> None:
    reg = MetricsRegistry()

    with pytest.raises(ValueError, match="metric name"):
        reg.counter("bad-name")
    with pytest.raises(ValueError, match="'__' prefix is reserved"):
        reg.counter("__internal_total")
    with pytest.raises(ValueError, match="reserved for registry uptime"):
        reg.gauge("uptime_seconds")

    counter = reg.counter("valid_total")
    with pytest.raises(ValueError, match="label name"):
        counter.inc(**{"bad-label": "value"})
    with pytest.raises(ValueError, match="reserved '__' prefix"):
        counter.inc(**{"__private": "value"})

    histogram = reg.histogram("duration_seconds")
    with pytest.raises(ValueError, match="reserved by this metric type"):
        histogram.observe(1.0, le="caller-controlled")


def test_prometheus_special_values_are_canonical_and_histograms_reject_them() -> None:
    reg = MetricsRegistry()
    gauge = reg.gauge("special_value", "Special values")
    gauge.set(float("inf"), kind="positive")
    gauge.set(float("-inf"), kind="negative")
    gauge.set(float("nan"), kind="not_a_number")

    rendered = reg.render_prometheus()

    assert 'special_value{kind="negative"} -Inf\n' in rendered
    assert 'special_value{kind="not_a_number"} NaN\n' in rendered
    assert 'special_value{kind="positive"} +Inf\n' in rendered

    histogram = reg.histogram("histogram")
    with pytest.raises(ValueError, match="must be finite"):
        histogram.observe(float("inf"))
    with pytest.raises(ValueError, match="must be finite"):
        histogram.observe(float("nan"))


@pytest.mark.parametrize(
    "amount",
    [float("inf"), float("-inf"), float("nan")],
    ids=["positive-infinity", "negative-infinity", "nan"],
)
def test_counter_rejects_non_finite_increments(amount: float) -> None:
    counter = MetricsRegistry().counter("finite_counter_total")

    with pytest.raises(ValueError, match="finite and non-negative"):
        counter.inc(amount)

    assert counter.collect() == []


def test_counter_accepts_finite_non_negative_increments() -> None:
    counter = MetricsRegistry().counter("finite_counter_total")

    counter.inc(0, outcome="ok")
    counter.inc(2.5, outcome="ok")

    assert counter.collect() == [
        {
            "name": "finite_counter_total",
            "labels": {"outcome": "ok"},
            "value": 2.5,
        }
    ]


def test_empty_help_has_no_trailing_space_and_precedes_type() -> None:
    reg = MetricsRegistry()
    reg.counter("no_help_total").inc()

    lines = reg.render_prometheus().splitlines()

    assert lines[:3] == [
        "# HELP no_help_total",
        "# TYPE no_help_total counter",
        "no_help_total 1.0",
    ]


def test_prometheus_exposition_formats_bool_gauge_as_numeric() -> None:
    """Bool gauge values must not render as Python ``True``/``False`` literals."""
    reg = MetricsRegistry()
    gauge = reg.gauge("enabled", "Feature flag")
    gauge.set(True)  # type: ignore[arg-type]
    gauge.set(False, mode="shadow")  # type: ignore[arg-type]

    rendered = reg.render_prometheus()

    assert "enabled True\n" not in rendered
    assert "enabled False\n" not in rendered
    assert "enabled 1.0\n" in rendered
    assert 'enabled{mode="shadow"} 0.0\n' in rendered


def test_empty_registry_exposes_only_uptime(monkeypatch: pytest.MonkeyPatch) -> None:
    monotonic_values = iter((10.0, 12.34))
    monkeypatch.setattr(metrics_module.time, "monotonic", lambda: next(monotonic_values))
    reg = MetricsRegistry()

    assert reg.render_prometheus() == (
        "# HELP uptime_seconds Time elapsed since this metrics registry was created\n"
        "# TYPE uptime_seconds gauge\n"
        "uptime_seconds 2.3\n"
    )
