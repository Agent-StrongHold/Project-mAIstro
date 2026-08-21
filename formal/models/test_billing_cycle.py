"""I21: Billing Cycle — Cycle Keys and Daily Budget — Hypothesis property-based tests."""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.quota.billing import cycle_key, daily_budget


_DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTHLY_RE = re.compile(r"^\d{4}-\d{2}$")


class BillingCycleMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.daily_keys: list[str] = []
        self.monthly_keys: list[str] = []

    @rule()
    def generate_daily_key(self):
        key = cycle_key("daily")
        self.daily_keys.append(key)
        assert _DAILY_RE.match(key)

    @rule()
    def generate_monthly_key(self):
        key = cycle_key("monthly")
        self.monthly_keys.append(key)
        assert _MONTHLY_RE.match(key)

    @invariant()
    def daily_keys_valid_format(self):
        for key in self.daily_keys:
            assert _DAILY_RE.match(key)

    @invariant()
    def monthly_keys_valid_format(self):
        for key in self.monthly_keys:
            assert _MONTHLY_RE.match(key)


TestBillingCycleMachine = BillingCycleMachine.TestCase


def test_daily_key_format():
    key = cycle_key("daily")
    assert _DAILY_RE.match(key)


def test_monthly_key_format():
    key = cycle_key("monthly")
    assert _MONTHLY_RE.match(key)


@given(cycle=st.just("daily"))
@settings(max_examples=10)
def test_daily_key_matches_regex(cycle):
    key = cycle_key(cycle)
    assert _DAILY_RE.match(key)


@given(cycle=st.just("monthly"))
@settings(max_examples=10)
def test_monthly_key_matches_regex(cycle):
    key = cycle_key(cycle)
    assert _MONTHLY_RE.match(key)


def test_daily_budget_daily():
    result = daily_budget(1000, "daily")
    assert result == 1000.0


def test_daily_budget_monthly():
    result = daily_budget(30000, "monthly")
    assert result == 30000.0 / 30.0


@given(
    free_tokens=st.integers(min_value=1, max_value=1000000),
)
@settings(max_examples=50)
def test_daily_budget_equals_free_tokens_daily(free_tokens):
    result = daily_budget(free_tokens, "daily")
    assert result == float(free_tokens)


@given(
    free_tokens=st.integers(min_value=1, max_value=1000000),
)
@settings(max_examples=50)
def test_daily_budget_equals_free_tokens_div_30_monthly(free_tokens):
    result = daily_budget(free_tokens, "monthly")
    assert abs(result - free_tokens / 30.0) < 0.001


def test_daily_budget_zero_tokens():
    assert daily_budget(0, "daily") == 0.0
    assert daily_budget(0, "monthly") == 0.0


@given(cycle=st.sampled_from(["daily", "monthly"]))
@settings(max_examples=10)
def test_cycle_key_deterministic_within_cycle(cycle):
    key1 = cycle_key(cycle)
    key2 = cycle_key(cycle)
    assert key1 == key2


def test_daily_key_components():
    key = cycle_key("daily")
    parts = key.split("-")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
    assert len(parts[0]) == 4
    assert len(parts[1]) == 2
    assert len(parts[2]) == 2


def test_monthly_key_components():
    key = cycle_key("monthly")
    parts = key.split("-")
    assert len(parts) == 2
    assert all(p.isdigit() for p in parts)
    assert len(parts[0]) == 4
    assert len(parts[1]) == 2
