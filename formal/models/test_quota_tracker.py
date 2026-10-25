"""I17: Quota Tracker — Token Usage Tracking — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.quota.billing import cycle_key
from maistro.quota.tracker import InMemoryQuotaTracker


def _run(coro):
    return asyncio.run(coro)


class QuotaTrackerMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.tracker = InMemoryQuotaTracker()
        self.provider = "test-provider"
        self.cycle = "daily"
        self.recorded_input = 0
        self.recorded_output = 0
        self.call_count = 0

    @rule(
        inp=st.integers(min_value=0, max_value=1000),
        out=st.integers(min_value=0, max_value=1000),
    )
    def record(self, inp, out):
        _run(self.tracker.record_usage(self.provider, self.cycle, inp, out))
        self.recorded_input += inp
        self.recorded_output += out
        self.call_count += 1

    @invariant()
    def total_equals_input_plus_output(self):
        usage = _run(self.tracker.get_all_usage())
        for entry in usage:
            total = entry["input_tokens"] + entry["output_tokens"]
            assert entry["total_tokens"] == total

    @invariant()
    def request_count_matches_calls(self):
        usage = _run(self.tracker.get_all_usage())
        for entry in usage:
            if entry.get("provider") == self.provider:
                assert entry["request_count"] == self.call_count


TestQuotaTrackerMachine = QuotaTrackerMachine.TestCase


@given(
    recordings=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=500),
            st.integers(min_value=0, max_value=500),
        ),
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=30)
def test_accumulated_totals(recordings):
    tracker = InMemoryQuotaTracker()
    total_input = 0
    total_output = 0
    for inp, out in recordings:
        _run(tracker.record_usage("prov", "daily", inp, out))
        total_input += inp
        total_output += out

    usage = _run(tracker.get_all_usage())
    assert len(usage) == 1
    assert usage[0]["input_tokens"] == total_input
    assert usage[0]["output_tokens"] == total_output
    assert usage[0]["total_tokens"] == total_input + total_output


@given(
    prov_a=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    prov_b=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
)
@settings(max_examples=20)
def test_different_providers_tracked_independently(prov_a, prov_b):
    assume(prov_a != prov_b)
    tracker = InMemoryQuotaTracker()
    _run(tracker.record_usage(prov_a, "daily", 100, 50))
    _run(tracker.record_usage(prov_b, "daily", 200, 75))

    usage = _run(tracker.get_all_usage())
    assert len(usage) == 2


@given(
    inp=st.integers(min_value=0, max_value=1000),
    out=st.integers(min_value=0, max_value=1000),
    free=st.integers(min_value=1, max_value=10000),
)
@settings(max_examples=50)
def test_usage_pct(inp, out, free):
    tracker = InMemoryQuotaTracker()
    _run(tracker.record_usage("p", "daily", inp, out))
    pct = _run(tracker.get_usage_pct("p", "daily", free))
    expected = (inp + out) / free
    assert abs(pct - expected) < 0.001


def test_usage_pct_free_tokens_zero():
    tracker = InMemoryQuotaTracker()
    _run(tracker.record_usage("p", "daily", 100, 50))
    pct = _run(tracker.get_usage_pct("p", "daily", 0))
    assert pct == 0.0


@given(
    n=st.integers(min_value=1, max_value=20),
)
@settings(max_examples=20)
def test_request_count_matches_calls(n):
    tracker = InMemoryQuotaTracker()
    for _ in range(n):
        _run(tracker.record_usage("p", "daily", 10, 5))
    usage = _run(tracker.get_all_usage())
    assert usage[0]["request_count"] == n


@given(
    inp=st.integers(min_value=0, max_value=1000),
    out=st.integers(min_value=0, max_value=1000),
)
@settings(max_examples=50)
def test_total_equals_input_plus_output(inp, out):
    tracker = InMemoryQuotaTracker()
    _run(tracker.record_usage("p", "daily", inp, out))
    usage = _run(tracker.get_all_usage())
    assert usage[0]["total_tokens"] == usage[0]["input_tokens"] + usage[0]["output_tokens"]


@given(
    free=st.integers(min_value=1, max_value=10000),
)
@settings(max_examples=20)
def test_no_usage_pct_is_zero(free):
    tracker = InMemoryQuotaTracker()
    pct = _run(tracker.get_usage_pct("unused", "daily", free))
    assert pct == 0.0


@given(
    billing_cycle=st.sampled_from(["daily", "monthly"]),
)
@settings(max_examples=10)
def test_cycle_key_applied(billing_cycle):
    tracker = InMemoryQuotaTracker()
    result = _run(tracker.record_usage("p", billing_cycle, 10, 5))
    assert result["cycle_key"] == cycle_key(billing_cycle)
