"""ADR-038 §4: error-budget accounting and burn-rate math.

The ADR's verification section calls for property tests on the burn-rate
math, so the invariants are Hypothesis properties; the throttle contract and
gauge publication get example-based locks.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from maistro.resilience.slo import (
    ErrorBudget,
    SloDefinition,
    maistro_slo_remaining_budget_seconds,
)

_WINDOW = 30 * 24 * 3600.0


def _budget(
    target: float = 0.999,
    *,
    window_seconds: float = _WINDOW,
) -> ErrorBudget:
    return ErrorBudget(
        SloDefinition(
            service_key="svc",
            slo="availability",
            target=target,
            window_seconds=window_seconds,
        )
    )


# --- definition -------------------------------------------------------------


def test_total_budget_is_the_tolerated_unavailability() -> None:
    definition = SloDefinition(
        service_key="svc", slo="availability", target=0.999, window_seconds=_WINDOW
    )
    assert definition.total_budget_seconds == pytest.approx(0.001 * _WINDOW)


@pytest.mark.parametrize("target", [0.0, 1.0, -0.5, 1.5])
def test_target_must_be_a_strict_ratio(target: float) -> None:
    with pytest.raises(ValueError):
        SloDefinition(service_key="svc", slo="availability", target=target)


@pytest.mark.parametrize("window_seconds", [0.0, -1.0, math.inf, -math.inf, math.nan])
def test_window_must_be_positive_and_finite(window_seconds: float) -> None:
    with pytest.raises(ValueError):
        SloDefinition(
            service_key="svc",
            slo="availability",
            target=0.999,
            window_seconds=window_seconds,
        )


# --- budget accounting (properties) ------------------------------------------


@given(
    downtimes=st.lists(st.floats(min_value=0.0, max_value=600.0), max_size=20),
)
def test_consumed_plus_remaining_covers_the_budget(downtimes: list[float]) -> None:
    budget = _budget()
    now = 1_000_000.0
    for i, seconds in enumerate(downtimes):
        budget.record_downtime(seconds, now=now + i)
    at = now + len(downtimes)
    consumed = budget.consumed_seconds(now=at)
    remaining = budget.remaining_seconds(now=at)
    assert consumed == pytest.approx(sum(downtimes))
    assert remaining == pytest.approx(max(0.0, budget.definition.total_budget_seconds - consumed))
    assert remaining >= 0.0


@given(
    interval_end=st.integers(min_value=0, max_value=10_000),
    seconds=st.integers(min_value=0, max_value=10_000),
    at=st.integers(min_value=0, max_value=10_000),
    window=st.integers(min_value=1, max_value=10_000),
)
def test_consumed_seconds_equals_interval_overlap(
    interval_end: int,
    seconds: int,
    at: int,
    window: int,
) -> None:
    budget = _budget(window_seconds=float(window))
    budget.record_downtime(float(seconds), now=float(interval_end))

    expected = max(
        0.0,
        min(float(interval_end), float(at))
        - max(float(interval_end - seconds), float(at - window)),
    )
    assert budget.consumed_seconds(now=float(at)) == pytest.approx(expected)


@given(
    interval_end=st.integers(min_value=0, max_value=10_000),
    seconds=st.integers(min_value=0, max_value=10_000),
    at=st.integers(min_value=0, max_value=10_000),
    window=st.integers(min_value=1, max_value=10_000),
    lookback=st.integers(min_value=1, max_value=10_000),
)
def test_burn_rate_counts_overlap_with_both_windows(
    interval_end: int,
    seconds: int,
    at: int,
    window: int,
    lookback: int,
) -> None:
    budget = _budget(target=0.9, window_seconds=float(window))
    budget.record_downtime(float(seconds), now=float(interval_end))

    effective_lookback = min(lookback, window)
    effective_start = float(at - effective_lookback)
    expected_consumed = max(
        0.0,
        min(float(interval_end), float(at)) - max(float(interval_end - seconds), effective_start),
    )
    allowance = budget.definition.total_budget_seconds * (effective_lookback / window)
    assert budget.burn_rate(
        lookback_seconds=float(lookback),
        now=float(at),
    ) == pytest.approx(expected_consumed / allowance)


@given(seconds=st.floats(min_value=0.001, max_value=600.0))
def test_burn_rate_is_linear_in_downtime(seconds: float) -> None:
    now = 1_000_000.0
    single = _budget()
    single.record_downtime(seconds, now=now)
    double = _budget()
    double.record_downtime(seconds, now=now)
    double.record_downtime(seconds, now=now)
    at = now + 1.0
    assert double.burn_rate(now=at) == pytest.approx(2 * single.burn_rate(now=at))


@given(lookback=st.floats(min_value=60.0, max_value=86_400.0))
def test_burn_rate_one_means_exactly_on_allowance(lookback: float) -> None:
    """Consuming exactly the steady allowance for a lookback is burn rate 1."""
    budget = _budget()
    now = 1_000_000.0
    allowance = budget.definition.total_budget_seconds * (lookback / _WINDOW)
    budget.record_downtime(allowance, now=now)
    assert budget.burn_rate(lookback_seconds=lookback, now=now + 1.0) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("interval_end", "seconds", "expected"),
    [
        (110.0, 20.0, 10.0),
        (210.0, 20.0, 10.0),
    ],
)
def test_partial_intervals_are_clipped_at_both_compliance_boundaries(
    interval_end: float,
    seconds: float,
    expected: float,
) -> None:
    budget = _budget(window_seconds=100.0)
    budget.record_downtime(seconds, now=interval_end)
    assert budget.consumed_seconds(now=200.0) == pytest.approx(expected)


def test_two_hour_interval_counts_one_hour_in_hourly_lookback() -> None:
    budget = _budget(window_seconds=4 * 3600.0)
    now = 10_000.0
    budget.record_downtime(2 * 3600.0, now=now)

    lookback = 3600.0
    allowance = budget.definition.total_budget_seconds * (
        lookback / budget.definition.window_seconds
    )
    assert budget.burn_rate(lookback_seconds=lookback, now=now) == pytest.approx(
        lookback / allowance
    )


def test_longer_requested_lookback_cannot_underreport_burn_rate() -> None:
    budget = _budget(target=0.9, window_seconds=100.0)
    now = 200.0
    budget.record_downtime(budget.definition.total_budget_seconds, now=now)

    compliance_window_rate = budget.burn_rate(lookback_seconds=100.0, now=now)
    longer_lookback_rate = budget.burn_rate(lookback_seconds=1000.0, now=now)

    assert compliance_window_rate == pytest.approx(1.0)
    assert longer_lookback_rate == pytest.approx(compliance_window_rate)


def test_multiple_intervals_sum_their_individual_overlaps() -> None:
    budget = _budget(window_seconds=100.0)
    budget.record_downtime(20.0, now=120.0)
    budget.record_downtime(30.0, now=180.0)
    assert budget.consumed_seconds(now=200.0) == pytest.approx(50.0)


@pytest.mark.parametrize(
    ("interval_end", "seconds", "expected"),
    [
        (100.0, 20.0, 0.0),
        (125.0, 25.0, 25.0),
        (200.0, 25.0, 25.0),
        (225.0, 25.0, 0.0),
    ],
)
def test_compliance_window_exact_edges(
    interval_end: float,
    seconds: float,
    expected: float,
) -> None:
    budget = _budget(window_seconds=100.0)
    budget.record_downtime(seconds, now=interval_end)
    assert budget.consumed_seconds(now=200.0) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("interval_end", "seconds", "expected_consumed"),
    [
        (150.0, 20.0, 0.0),
        (175.0, 25.0, 25.0),
        (200.0, 25.0, 25.0),
        (225.0, 25.0, 0.0),
    ],
)
def test_lookback_exact_edges(
    interval_end: float,
    seconds: float,
    expected_consumed: float,
) -> None:
    budget = _budget(target=0.9, window_seconds=1000.0)
    budget.record_downtime(seconds, now=interval_end)
    allowance = budget.definition.total_budget_seconds * (50.0 / 1000.0)
    assert budget.burn_rate(lookback_seconds=50.0, now=200.0) == pytest.approx(
        expected_consumed / allowance
    )


def test_downtime_outside_the_window_restores_budget() -> None:
    budget = _budget()
    now = 1_000_000.0
    budget.record_downtime(120.0, now=now)
    assert budget.consumed_seconds(now=now + 1) == pytest.approx(120.0)
    after_window = now + _WINDOW + 1.0
    assert budget.consumed_seconds(now=after_window) == 0.0
    assert budget.remaining_seconds(now=after_window) == pytest.approx(
        budget.definition.total_budget_seconds
    )


def test_recovery_prunes_intervals_outside_the_compliance_window() -> None:
    budget = _budget(window_seconds=100.0)
    budget.record_downtime(20.0, now=50.0)
    budget.record_downtime(20.0, now=100.0)
    assert len(budget._downtime) == 2

    assert budget.consumed_seconds(now=150.0) == pytest.approx(20.0)
    assert len(budget._downtime) == 1

    assert budget.consumed_seconds(now=200.0) == 0.0
    assert not budget._downtime


@pytest.mark.parametrize("seconds", [-1.0, math.inf, -math.inf, math.nan])
def test_invalid_downtime_is_rejected(seconds: float) -> None:
    with pytest.raises(ValueError):
        _budget().record_downtime(seconds)


@pytest.mark.parametrize("now", [-1.0, math.inf, -math.inf, math.nan])
def test_invalid_timestamps_are_rejected(now: float) -> None:
    with pytest.raises(ValueError):
        _budget().record_downtime(1.0, now=now)


@pytest.mark.parametrize("lookback", [0.0, -1.0, math.inf, -math.inf, math.nan])
def test_invalid_lookbacks_are_rejected(lookback: float) -> None:
    with pytest.raises(ValueError):
        _budget().burn_rate(lookback_seconds=lookback, now=100.0)


# --- throttle contract --------------------------------------------------------


def test_throttles_above_double_burn_sustained_over_the_lookback() -> None:
    """ADR-038: burn rate over 2x across the 1h lookback throttles; at or
    below 2x it does not."""
    now = 1_000_000.0
    hourly_allowance = _budget().definition.total_budget_seconds * (3600.0 / _WINDOW)

    at_double = _budget()
    at_double.record_downtime(2.0 * hourly_allowance, now=now)
    assert not at_double.should_throttle(now=now + 1.0)

    beyond_double = _budget()
    beyond_double.record_downtime(2.5 * hourly_allowance, now=now)
    assert beyond_double.should_throttle(now=now + 1.0)

    # The same downtime an hour later has aged out of the lookback.
    assert not beyond_double.should_throttle(now=now + 3601.0)


# --- gauge publication ----------------------------------------------------------


def test_recording_publishes_remaining_budget_gauge() -> None:
    budget = ErrorBudget(SloDefinition(service_key="gauge-svc", slo="availability", target=0.999))
    now = 1_000_000.0
    budget.record_downtime(60.0, now=now)
    expected = budget.definition.total_budget_seconds - 60.0
    samples = {
        (s["labels"]["service_key"], s["labels"]["slo"]): s["value"]
        for s in maistro_slo_remaining_budget_seconds.collect()
    }
    assert samples[("gauge-svc", "availability")] == pytest.approx(expected)


def test_the_periodic_throttle_check_refreshes_a_recovered_budget() -> None:
    """Budget recovery is time-driven: downtime ages out with no new event to
    record. A gauge written only on record_downtime would sit at its depleted
    value forever after a service healed."""
    budget = ErrorBudget(SloDefinition(service_key="recovering", slo="availability", target=0.999))
    now = 1_000_000.0
    budget.record_downtime(600.0, now=now)
    depleted = _gauge("recovering")
    assert depleted == pytest.approx(budget.definition.total_budget_seconds - 600.0)

    # The window rolls; nothing new is recorded.
    later = now + _WINDOW + 1.0
    budget.should_throttle(now=later)
    assert _gauge("recovering") == pytest.approx(budget.definition.total_budget_seconds)
    assert _gauge("recovering") > depleted


def _gauge(service_key: str) -> float:
    for sample in maistro_slo_remaining_budget_seconds.collect():
        if sample["labels"]["service_key"] == service_key:
            return float(sample["value"])
    raise AssertionError(f"no gauge sample for {service_key!r}")
