"""Circuit breaker for LLM provider calls.

Prevents cascading failures by fast-failing when the LLM provider
is down, instead of exhausting retries on every request.

States:
- CLOSED: Normal operation, requests go through
- OPEN: Provider is down, requests fail immediately
- HALF_OPEN: Testing recovery with a single request
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from enum import StrEnum
from functools import partial
from typing import Any

import structlog

from maistro.config.settings import Settings, get_settings
from maistro.observability.metrics import maistro_circuit_state
from maistro.security.resource_policy import (
    BASELINE_CIRCUIT_FAILURE_THRESHOLD,
    BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
)

logger = structlog.get_logger()

_DEFAULT_FAILURE_WINDOW_S = 60.0


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ADR-037 gauge encoding: 0=closed, 1=half-open, 2=open.
_CIRCUIT_GAUGE_VALUE = {
    CircuitState.CLOSED: 0,
    CircuitState.HALF_OPEN: 1,
    CircuitState.OPEN: 2,
}


class CircuitBreaker:
    """Thread-safe circuit breaker for one upstream dependency.

    Failures are retained in a bounded rolling window. ``allow_request`` is an
    atomic admission boundary: CLOSED admits normal traffic, OPEN rejects it,
    and HALF_OPEN leases exactly one probe to the calling thread/asyncio task.

    Async probe leases are released when their owning task finishes without
    recording a result. Any other abandoned lease safely reopens the circuit
    after ``probe_timeout`` so a missing result cannot wedge HALF_OPEN forever.
    """

    def __init__(
        self,
        failure_threshold: int = BASELINE_CIRCUIT_FAILURE_THRESHOLD,
        recovery_timeout: float = BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
        name: str = "llm",
        *,
        failure_window: float = _DEFAULT_FAILURE_WINDOW_S,
        probe_timeout: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if (
            isinstance(failure_threshold, bool)
            or not isinstance(failure_threshold, int)
            or failure_threshold <= 0
        ):
            raise ValueError("failure_threshold must be a positive integer")
        self._validate_duration("recovery_timeout", recovery_timeout)
        self._validate_duration("failure_window", failure_window)
        effective_probe_timeout = recovery_timeout if probe_timeout is None else probe_timeout
        self._validate_duration("probe_timeout", effective_probe_timeout)
        if clock is not None and not callable(clock):
            raise ValueError("clock must be callable")

        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = float(recovery_timeout)
        self.failure_window = float(failure_window)
        self.probe_timeout = float(effective_probe_timeout)
        self._clock = time.monotonic if clock is None else clock
        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._failures: deque[float] = deque(maxlen=failure_threshold)
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0
        self._probe_owner: tuple[int, asyncio.Task[Any] | None] | None = None
        self._probe_started_at: float | None = None
        self._probe_generation = 0
        self._active_probe_generation: int | None = None
        self._probe_task: asyncio.Task[Any] | None = None
        self._probe_done_callback: Callable[[asyncio.Task[Any]], None] | None = None
        self._publish_state()

    @staticmethod
    def _validate_duration(name: str, value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{name} must be finite and positive")

    def _now(self) -> float:
        value = self._clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("clock must return a finite number")
        return float(value)

    @staticmethod
    def _caller_identity() -> tuple[int, asyncio.Task[Any] | None]:
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
        return threading.get_ident(), task

    def _publish_state(self) -> None:
        maistro_circuit_state.set(_CIRCUIT_GAUGE_VALUE[self._state], dependency=self.name)

    def _set_state_locked(self, state: CircuitState) -> None:
        if state == self._state:
            return
        self._state = state
        self._publish_state()

    def _clear_probe_locked(self) -> None:
        if self._probe_task is not None and self._probe_done_callback is not None:
            self._probe_task.remove_done_callback(self._probe_done_callback)
        self._probe_task = None
        self._probe_done_callback = None
        self._probe_owner = None
        self._probe_started_at = None
        self._active_probe_generation = None

    def _release_finished_probe(
        self,
        generation: int,
        _task: asyncio.Task[Any],
    ) -> None:
        with self._lock:
            if (
                self._state == CircuitState.HALF_OPEN
                and self._active_probe_generation == generation
            ):
                self._clear_probe_locked()
                logger.info("circuit_probe_released", name=self.name, reason="owner_finished")

    def _claim_probe_locked(self, now: float) -> None:
        owner = self._caller_identity()
        self._probe_generation += 1
        generation = self._probe_generation
        self._probe_owner = owner
        self._probe_started_at = now
        self._active_probe_generation = generation
        task = owner[1]
        if task is not None:
            callback = partial(self._release_finished_probe, generation)
            self._probe_task = task
            self._probe_done_callback = callback
            task.add_done_callback(callback)

    def _prune_failures_locked(self, now: float) -> None:
        # The boundary is inclusive: a failure exactly W seconds old remains in
        # [now-W, now], while the first instant after W expires it.
        cutoff = now - self.failure_window
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()
        self._failure_count = len(self._failures)

    def _open_locked(self, now: float, *, reason: str) -> None:
        was_open = self._state == CircuitState.OPEN
        self._last_failure_time = now
        self._clear_probe_locked()
        self._set_state_locked(CircuitState.OPEN)
        if not was_open:
            logger.warning(
                "circuit_opened",
                name=self.name,
                failure_count=self._failure_count,
                recovery_timeout=self.recovery_timeout,
                reason=reason,
            )

    def _refresh_state_locked(self, now: float) -> None:
        if (
            self._state == CircuitState.OPEN
            and now - self._last_failure_time >= self.recovery_timeout
        ):
            self._clear_probe_locked()
            self._set_state_locked(CircuitState.HALF_OPEN)
            logger.info("circuit_half_open", name=self.name)
            return

        if (
            self._state == CircuitState.HALF_OPEN
            and self._active_probe_generation is not None
            and self._probe_started_at is not None
            and now - self._probe_started_at >= self.probe_timeout
        ):
            logger.warning("circuit_probe_abandoned", name=self.name)
            self._open_locked(now, reason="probe_timeout")

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._refresh_state_locked(self._now())
            return self._state

    def allow_request(self) -> bool:
        """Atomically admit normal traffic or claim the sole HALF_OPEN probe."""
        with self._lock:
            now = self._now()
            self._refresh_state_locked(now)
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN or self._active_probe_generation is not None:
                return False
            self._claim_probe_locked(now)
            return True

    def record_success(self) -> None:
        """Record a successful call.

        In HALF_OPEN, this closes the circuit only for the same thread or
        asyncio task whose ``allow_request()`` call acquired the current
        exclusive probe lease. Success reported by any other caller is ignored.
        """
        owner = self._caller_identity()
        with self._lock:
            self._refresh_state_locked(self._now())
            self._success_count += 1
            if self._state == CircuitState.CLOSED:
                self._failures.clear()
                self._failure_count = 0
                self._last_failure_time = 0.0
                return
            if self._state != CircuitState.HALF_OPEN:
                return
            if self._probe_owner != owner:
                logger.debug("circuit_stale_success_ignored", name=self.name)
                return

            logger.info("circuit_closed", name=self.name)
            self._failures.clear()
            self._failure_count = 0
            self._last_failure_time = 0.0
            self._clear_probe_locked()
            self._set_state_locked(CircuitState.CLOSED)

    def record_failure(self) -> None:
        """Record a failure in W; a failed HALF_OPEN probe always reopens."""
        with self._lock:
            now = self._now()
            self._prune_failures_locked(now)
            self._failures.append(now)
            self._failure_count = len(self._failures)
            self._last_failure_time = now

            if self._state == CircuitState.HALF_OPEN:
                self._open_locked(now, reason="probe_failure")
            elif self._state == CircuitState.OPEN:
                # A late in-flight failure restarts the cooldown without
                # publishing a duplicate state transition.
                self._clear_probe_locked()
            elif self._failure_count >= self.failure_threshold:
                self._open_locked(now, reason="failure_threshold")

    def release_probe(self) -> None:
        """Release the caller's HALF_OPEN lease after cancellation or abandonment.

        Async task completion also performs this release automatically. This
        explicit form supports cancellation that is caught inside a long-lived
        task and synchronous callers that cannot use task completion cleanup.
        """
        owner = self._caller_identity()
        with self._lock:
            if self._state == CircuitState.HALF_OPEN and self._probe_owner == owner:
                self._clear_probe_locked()
                logger.info("circuit_probe_released", name=self.name, reason="caller_release")


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open."""

    def __init__(self, breaker: CircuitBreaker) -> None:
        super().__init__(
            f"Circuit breaker '{breaker.name}' is open — "
            f"provider reached {breaker.failure_threshold} failures "
            f"within {breaker.failure_window:g}s"
        )


def circuit_breaker_from_settings(settings: Settings | None = None) -> CircuitBreaker:
    """Construct the process LLM circuit from validated deployment policy."""
    effective = settings or get_settings()
    return CircuitBreaker(
        name="llm_provider",
        failure_threshold=effective.circuit_breaker_failure_threshold,
        recovery_timeout=effective.circuit_breaker_recovery_timeout_s,
    )


# Global circuit breaker for the LLM provider. Settings validation enforces the
# security floor before these values can become runtime behavior.
llm_circuit = circuit_breaker_from_settings()
