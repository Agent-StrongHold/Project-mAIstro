"""Tests for CircuitBreaker."""

from __future__ import annotations

import time

import pytest

from maistro.agents.circuit_breaker import CircuitBreaker, CircuitState


def test_initial_state_is_closed():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
    assert cb.state == "closed"
    assert cb.allow_request()


def test_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "open"
    assert not cb.allow_request()


def test_success_resets_failures():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.state == "closed"
    assert cb.allow_request()


def test_half_open_after_recovery(monkeypatch: object):
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"

    # Wait for recovery timeout
    time.sleep(0.02)
    assert cb.state == "half_open"
    assert cb.allow_request()


def test_half_open_success_closes():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
    cb.record_failure()
    time.sleep(0.02)
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"


def test_half_open_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
    cb.record_failure()
    time.sleep(0.02)
    assert cb.state == "half_open"
    cb.record_failure()
    assert cb.state == "open"


class _FakeClock:
    """Callable stand-in for time.monotonic with explicit, test-controlled advance."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    fake = _FakeClock()
    monkeypatch.setattr(time, "monotonic", fake)
    return fake


class TestStateEventMatrix:
    """Independently-derived (state x event) grid for CircuitBreaker.

    Events: record_success, record_failure, time elapsed below recovery_timeout,
    time elapsed at/past recovery_timeout. Driven by a monkeypatched
    time.monotonic so the HALF_OPEN boundary is exact rather than a real-time race.

    CLOSED   x success            -> CLOSED   (failure count reset)
    CLOSED   x failure (<thresh)  -> CLOSED
    CLOSED   x failure (=thresh)  -> OPEN
    CLOSED   x time elapsed       -> CLOSED   (no-op; check only applies to OPEN)
    OPEN     x time < recovery    -> OPEN
    OPEN     x time >= recovery   -> HALF_OPEN (lazy transition on next .state read)
    OPEN     x failure            -> OPEN     (and resets the recovery clock)
    OPEN     x success            -> OPEN     (raw _state only closes from HALF_OPEN;
                                                 a success recorded before any .state
                                                 read loses the race to the lazy
                                                 OPEN->HALF_OPEN transition)
    HALF_OPEN x success           -> CLOSED
    HALF_OPEN x failure           -> OPEN     (failure_count was never reset)
    HALF_OPEN x time elapsed      -> HALF_OPEN (no further time-based transition)
    """

    def test_closed_success_stays_closed(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_closed_failure_below_threshold_stays_closed(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_closed_failure_at_threshold_opens(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_closed_time_elapsed_is_a_no_op(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        clock.advance(1000)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_open_time_below_recovery_stays_open(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        cb.record_failure()
        clock.advance(9.99)
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_open_time_at_recovery_boundary_transitions_half_open(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        cb.record_failure()
        clock.advance(10.0)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_open_failure_resets_recovery_clock(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        cb.record_failure()
        clock.advance(9.0)
        cb.record_failure()  # resets last_failure_time to "now"
        clock.advance(9.0)  # only 9s since the *second* failure
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_open_success_before_state_refresh_does_not_close(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        cb.record_failure()
        clock.advance(20.0)  # well past recovery_timeout, but .state not yet read
        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_half_open_success_closes(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        cb.record_failure()
        clock.advance(10.0)
        state_before = cb.state
        assert state_before == CircuitState.HALF_OPEN
        cb.record_success()
        state_after = cb.state
        assert state_after == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_half_open_failure_reopens(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        cb.record_failure()
        clock.advance(10.0)
        state_before = cb.state
        assert state_before == CircuitState.HALF_OPEN
        cb.record_failure()
        state_after = cb.state
        assert state_after == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_half_open_time_elapsed_is_a_no_op(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        cb.record_failure()
        clock.advance(10.0)
        assert cb.state == CircuitState.HALF_OPEN
        clock.advance(1_000_000.0)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True
