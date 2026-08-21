"""I2: Sliding Window Rate Limiting — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security._types import RateLimitConfig
from maistro.security.rate_limiter import InMemoryRateLimiter


def _run(coro):
    return asyncio.run(coro)


class RateLimiterMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.rpm = 10
        self.config = RateLimitConfig(
            requests_per_minute=self.rpm,
            burst_limit=self.rpm,
            enabled=True,
        )
        self.limiter = InMemoryRateLimiter(config=self.config)
        self.key = "test-key"
        self.recorded = 0

    @rule()
    def record_request(self):
        _run(self.limiter.record(self.key))
        self.recorded += 1

    @invariant()
    def check_after_rpm_exceeded(self):
        if self.recorded >= self.rpm:
            ok, _ = _run(self.limiter.check(self.key))
            assert not ok

    @invariant()
    def check_below_rpm_allowed(self):
        if self.recorded < self.rpm:
            ok, _ = _run(self.limiter.check(self.key))
            assert ok


TestRateLimiterMachine = RateLimiterMachine.TestCase


@given(
    rpm=st.integers(min_value=1, max_value=100),
    burst=st.integers(min_value=1, max_value=50),
    n=st.integers(min_value=0, max_value=200),
)
@settings(max_examples=60)
def test_rpm_enforcement(rpm, burst, n):
    effective_burst = max(burst, rpm)
    config = RateLimitConfig(requests_per_minute=rpm, burst_limit=effective_burst, enabled=True)
    limiter = InMemoryRateLimiter(config=config)

    for _ in range(n):
        _run(limiter.record("key-1"))

    ok, _ = _run(limiter.check("key-1"))
    if n >= rpm:
        assert not ok
    else:
        assert ok


@given(
    rpm=st.integers(min_value=20, max_value=100),
    burst=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=50)
def test_burst_enforcement(rpm, burst):
    config = RateLimitConfig(requests_per_minute=rpm, burst_limit=burst, enabled=True)
    limiter = InMemoryRateLimiter(config=config)

    for _ in range(burst):
        _run(limiter.record("burst-key"))

    ok, _ = _run(limiter.check("burst-key"))
    assert not ok


@given(
    key_a=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N"))),
    key_b=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N"))),
    rpm=st.integers(min_value=5, max_value=20),
)
@settings(max_examples=50)
def test_independent_keys(key_a, key_b, rpm):
    assume(key_a != key_b)
    config = RateLimitConfig(requests_per_minute=rpm, burst_limit=rpm, enabled=True)
    limiter = InMemoryRateLimiter(config=config)

    for _ in range(rpm):
        _run(limiter.record(key_a))

    ok_a, _ = _run(limiter.check(key_a))
    ok_b, _ = _run(limiter.check(key_b))

    assert not ok_a
    assert ok_b


@given(
    rpm=st.integers(min_value=1, max_value=100),
    n=st.integers(min_value=0, max_value=200),
)
@settings(max_examples=50)
def test_disabled_allows_everything(rpm, n):
    config = RateLimitConfig(requests_per_minute=rpm, burst_limit=1, enabled=False)
    limiter = InMemoryRateLimiter(config=config)

    for _ in range(n):
        _run(limiter.record("disabled-key"))

    ok, headers = _run(limiter.check("disabled-key"))
    assert ok


@given(
    rpm=st.integers(min_value=2, max_value=50),
    n=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=50)
def test_headers_populated(rpm, n):
    config = RateLimitConfig(requests_per_minute=rpm, burst_limit=rpm, enabled=True)
    limiter = InMemoryRateLimiter(config=config)

    for _ in range(n):
        _run(limiter.record("hdr-key"))

    ok, headers = _run(limiter.check("hdr-key"))
    assert "X-RateLimit-Limit" in headers
    assert headers["X-RateLimit-Limit"] == str(rpm)
    assert "X-RateLimit-Remaining" in headers


@given(rpm=st.integers(min_value=5, max_value=30))
@settings(max_examples=30)
def test_remaining_decreases(rpm):
    config = RateLimitConfig(requests_per_minute=rpm, burst_limit=rpm, enabled=True)
    limiter = InMemoryRateLimiter(config=config)

    prev_remaining = rpm
    for i in range(rpm):
        ok, headers = _run(limiter.check("dec-key"))
        if not ok:
            break
        _run(limiter.record("dec-key"))
        remaining = int(headers["X-RateLimit-Remaining"])
        assert remaining <= prev_remaining
        prev_remaining = remaining


@given(
    rpm=st.integers(min_value=1, max_value=10),
    key=st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=("L",))),
)
@settings(max_examples=30)
def test_zero_requests_always_allowed(rpm, key):
    config = RateLimitConfig(requests_per_minute=rpm, burst_limit=rpm, enabled=True)
    limiter = InMemoryRateLimiter(config=config)

    ok, _ = _run(limiter.check(key))
    assert ok


@given(rpm=st.integers(min_value=2, max_value=20))
@settings(max_examples=30)
def test_exactly_rpm_minus_one_allowed(rpm):
    config = RateLimitConfig(requests_per_minute=rpm, burst_limit=rpm, enabled=True)
    limiter = InMemoryRateLimiter(config=config)

    for _ in range(rpm - 1):
        _run(limiter.record("exact-key"))

    ok, _ = _run(limiter.check("exact-key"))
    assert ok


@given(rpm=st.integers(min_value=2, max_value=20))
@settings(max_examples=30)
def test_exactly_rpm_denied(rpm):
    config = RateLimitConfig(requests_per_minute=rpm, burst_limit=rpm, enabled=True)
    limiter = InMemoryRateLimiter(config=config)

    for _ in range(rpm):
        _run(limiter.record("exact-key-2"))

    ok, _ = _run(limiter.check("exact-key-2"))
    assert not ok
