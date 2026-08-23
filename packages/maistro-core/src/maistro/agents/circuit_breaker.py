"""Circuit breaker for LLM provider calls.

Prevents cascading failures by fast-failing when the LLM provider
is down, instead of exhausting retries on every request.

States:
- CLOSED: Normal operation, requests go through
- OPEN: Provider is down, requests fail immediately
- HALF_OPEN: Testing recovery with a single request
"""

from __future__ import annotations

import time
from enum import StrEnum

import structlog

from maistro.config.settings import Settings, get_settings
from maistro.observability.metrics import maistro_circuit_state
from maistro.security.resource_policy import (
    BASELINE_CIRCUIT_FAILURE_THRESHOLD,
    BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
)

logger = structlog.get_logger()


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
    """Circuit breaker for LLM provider resilience."""

    def __init__(
        self,
        failure_threshold: int = BASELINE_CIRCUIT_FAILURE_THRESHOLD,
        recovery_timeout: float = BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
        name: str = "llm",
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0
        self._publish_state()

    def _publish_state(self) -> None:
        maistro_circuit_state.set(_CIRCUIT_GAUGE_VALUE[self._state], dependency=self.name)

    @property
    def state(self) -> CircuitState:
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._last_failure_time >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            self._publish_state()
            logger.info("circuit_half_open", name=self.name)
        return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        current = self.state
        return current in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("circuit_closed", name=self.name)
            self._state = CircuitState.CLOSED
            self._publish_state()
        self._failure_count = 0
        self._success_count += 1

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            if self._state != CircuitState.OPEN:
                logger.warning(
                    "circuit_opened",
                    name=self.name,
                    failure_count=self._failure_count,
                    recovery_timeout=self.recovery_timeout,
                )
            self._state = CircuitState.OPEN
            self._publish_state()


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open."""

    def __init__(self, breaker: CircuitBreaker) -> None:
        super().__init__(
            f"Circuit breaker '{breaker.name}' is open — "
            f"provider failing after {breaker.failure_threshold} consecutive errors"
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
