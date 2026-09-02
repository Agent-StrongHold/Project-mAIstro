"""Review regressions for exclusive circuit recovery probes (#828)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from maistro.agents.circuit_breaker import CircuitBreaker, CircuitState


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _LongLivedTask:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[Any], None]] = []

    def add_done_callback(self, callback: Callable[[Any], None]) -> None:
        self.callbacks.append(callback)

    def remove_done_callback(self, callback: Callable[[Any], None]) -> int:
        try:
            self.callbacks.remove(callback)
        except ValueError:
            return 0
        return 1


def test_expired_probe_success_cannot_close_without_intervening_poll() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout=10,
        probe_timeout=5,
        clock=clock,
    )
    breaker.record_failure()
    clock.advance(10)
    assert breaker.allow_request() is True

    clock.advance(5)
    breaker.record_success()

    assert breaker.state == CircuitState.OPEN


def test_releasing_probe_removes_long_lived_task_callback() -> None:
    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
    breaker.record_failure()
    clock.advance(10)
    task = _LongLivedTask()
    owner = (threading.get_ident(), task)
    breaker._caller_identity = lambda: owner  # type: ignore[method-assign,return-value]

    assert breaker.allow_request() is True
    assert len(task.callbacks) == 1

    breaker.release_probe()

    assert task.callbacks == []
    assert breaker.state == CircuitState.HALF_OPEN
