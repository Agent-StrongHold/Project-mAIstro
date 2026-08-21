"""Tests for CircuitBreaker."""

from __future__ import annotations

from maistro.agents.circuit_breaker import CircuitBreaker


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
    import time

    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"

    # Wait for recovery timeout
    time.sleep(0.02)
    assert cb.state == "half_open"
    assert cb.allow_request()


def test_half_open_success_closes():
    import time

    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
    cb.record_failure()
    time.sleep(0.02)
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"


def test_half_open_failure_reopens():
    import time

    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
    cb.record_failure()
    time.sleep(0.02)
    assert cb.state == "half_open"
    cb.record_failure()
    assert cb.state == "open"
