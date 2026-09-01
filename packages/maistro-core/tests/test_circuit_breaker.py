"""Tests for CircuitBreaker."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

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
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "closed"
    assert cb.allow_request()


def test_half_open_after_recovery(clock: _FakeClock):
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, clock=clock)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"

    clock.advance(10)
    assert cb.state == "half_open"
    assert cb.allow_request()


def test_half_open_success_closes(clock: _FakeClock):
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
    cb.record_failure()
    clock.advance(10)
    assert cb.state == "half_open"
    assert cb.allow_request()
    cb.record_success()
    assert cb.state == "closed"


def test_half_open_failure_reopens(clock: _FakeClock):
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
    cb.record_failure()
    clock.advance(10)
    assert cb.state == "half_open"
    assert cb.allow_request()
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
def clock() -> _FakeClock:
    return _FakeClock()


class TestSlidingFailureWindow:
    def test_spaced_failures_age_out(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(
            failure_threshold=3,
            failure_window=10,
            recovery_timeout=30,
            clock=clock,
        )

        for _ in range(3):
            cb.record_failure()
            clock.advance(10.01)

        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_exact_window_boundary_counts_but_next_instant_expires(self, clock: _FakeClock) -> None:
        at_boundary = CircuitBreaker(
            failure_threshold=2,
            failure_window=10,
            recovery_timeout=30,
            clock=clock,
        )
        at_boundary.record_failure()
        clock.advance(10)
        at_boundary.record_failure()
        assert at_boundary.state == CircuitState.OPEN

        just_outside = CircuitBreaker(
            failure_threshold=2,
            failure_window=10,
            recovery_timeout=30,
            clock=clock,
        )
        just_outside.record_failure()
        clock.advance(10.001)
        just_outside.record_failure()
        assert just_outside.state == CircuitState.CLOSED


class TestHalfOpenProbe:
    def test_unleased_success_cannot_close_half_open(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10)

        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN

    def test_exactly_one_concurrent_caller_claims_probe(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10)
        barrier = threading.Barrier(8)

        def attempt(_index: int) -> bool:
            barrier.wait()
            return cb.allow_request()

        with ThreadPoolExecutor(max_workers=8) as executor:
            admitted = list(executor.map(attempt, range(8)))

        assert admitted.count(True) == 1
        assert admitted.count(False) == 7
        assert cb.state == CircuitState.HALF_OPEN

    def test_successful_probe_closes_and_clears_failures(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(
            failure_threshold=2,
            failure_window=60,
            recovery_timeout=10,
            clock=clock,
        )
        cb.record_failure()
        cb.record_failure()
        clock.advance(10)

        assert cb.allow_request() is True
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_failed_probe_reopens_and_restarts_cooldown(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10)
        assert cb.allow_request() is True

        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        clock.advance(9.999)
        assert cb.allow_request() is False
        clock.advance(0.001)
        assert cb.allow_request() is True

    async def test_cancelled_async_probe_releases_lease(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10)
        claimed = asyncio.Event()
        wait_forever = asyncio.Event()

        async def probe() -> None:
            assert cb.allow_request() is True
            claimed.set()
            await wait_forever.wait()

        task = asyncio.create_task(probe())
        await claimed.wait()
        assert cb.allow_request() is False

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_release_probe_allows_another_caller_to_claim(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10)

        def claim_and_release() -> bool:
            claimed = cb.allow_request()
            cb.release_probe()
            return claimed

        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(claim_and_release).result() is True

        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    async def test_stale_probe_result_cannot_close_new_probe(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=10,
            probe_timeout=5,
            clock=clock,
        )
        cb.record_failure()
        clock.advance(10)
        old_claimed = asyncio.Event()
        finish_old = asyncio.Event()

        async def old_probe() -> None:
            assert cb.allow_request() is True
            old_claimed.set()
            await finish_old.wait()
            cb.record_success()

        old_task = asyncio.create_task(old_probe())
        await old_claimed.wait()
        clock.advance(5)
        assert cb.state == CircuitState.OPEN
        clock.advance(10)
        assert cb.allow_request() is True

        finish_old.set()
        await old_task
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_abandoned_probe_safely_reopens_after_lease_timeout(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=10,
            probe_timeout=5,
            clock=clock,
        )
        cb.record_failure()
        clock.advance(10)
        assert cb.allow_request() is True

        clock.advance(5)
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False
        clock.advance(10)
        assert cb.allow_request() is True
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


@pytest.mark.parametrize("value", [0, -1, True])
def test_invalid_failure_threshold_is_rejected(value: int) -> None:
    with pytest.raises(ValueError, match="failure_threshold"):
        CircuitBreaker(failure_threshold=value)


@pytest.mark.parametrize("field", ["recovery_timeout", "failure_window", "probe_timeout"])
@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_durations_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        CircuitBreaker(**{field: value})


def test_non_callable_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="clock"):
        CircuitBreaker(clock=0)  # type: ignore[arg-type]


class TestStateEventMatrix:
    """Independently-derived (state x event) grid for CircuitBreaker.

    Events: record_success, record_failure, time elapsed below recovery_timeout,
    time elapsed at/past recovery_timeout. Driven by an injected clock so the
    HALF_OPEN boundary is exact rather than a real-time race.

    CLOSED   x success            -> CLOSED   (failure window reset)
    CLOSED   x failure (<thresh)  -> CLOSED
    CLOSED   x failure (=thresh)  -> OPEN
    CLOSED   x time elapsed       -> CLOSED   (no-op; check only applies to OPEN)
    OPEN     x time < recovery    -> OPEN
    OPEN     x time >= recovery   -> HALF_OPEN (lazy transition on next .state read)
    OPEN     x failure            -> OPEN     (and resets the recovery clock)
    OPEN     x success            -> OPEN     (a late in-flight success cannot close)
    HALF_OPEN x success           -> CLOSED
    HALF_OPEN x failure           -> OPEN
    HALF_OPEN x time elapsed      -> HALF_OPEN (when no probe has been claimed)
    """

    def test_closed_success_stays_closed(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10, clock=clock)
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_closed_failure_below_threshold_stays_closed(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10, clock=clock)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_closed_failure_at_threshold_opens(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10, clock=clock)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_closed_time_elapsed_is_a_no_op(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10, clock=clock)
        clock.advance(1000)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_open_time_below_recovery_stays_open(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(9.99)
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_open_time_at_recovery_boundary_transitions_half_open(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10.0)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_open_failure_resets_recovery_clock(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(9.0)
        cb.record_failure()  # resets last_failure_time to "now"
        clock.advance(9.0)  # only 9s since the *second* failure
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_open_success_before_state_refresh_does_not_close(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(20.0)  # well past recovery_timeout, but .state not yet read
        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_success_closes(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10.0)
        state_before = cb.state
        assert state_before == CircuitState.HALF_OPEN
        assert cb.allow_request() is True
        cb.record_success()
        state_after = cb.state
        assert state_after == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_half_open_failure_reopens(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10.0)
        state_before = cb.state
        assert state_before == CircuitState.HALF_OPEN
        assert cb.allow_request() is True
        cb.record_failure()
        state_after = cb.state
        assert state_after == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_half_open_time_elapsed_is_a_no_op(self, clock: _FakeClock) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10.0)
        assert cb.state == CircuitState.HALF_OPEN
        clock.advance(1_000_000.0)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True
