"""ADR-038 §4: error-budget accounting and burn-rate math.

The ADR's verification section calls for property tests on the burn-rate
math, so the invariants are Hypothesis properties; the throttle contract and
gauge publication get example-based locks.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from maistro.resilience.slo import (
    ErrorBudget,
    SloDefinition,
    maistro_slo_remaining_budget_seconds,
)

_WINDOW = 30 * 24 * 3600.0


def _budget(target: float = 0.999) -> ErrorBudget:
    return ErrorBudget(SloDefinition(service_key="svc", slo="availability", target=target))


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


def test_negative_downtime_is_rejected() -> None:
    with pytest.raises(ValueError):
        _budget().record_downtime(-1.0)


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
