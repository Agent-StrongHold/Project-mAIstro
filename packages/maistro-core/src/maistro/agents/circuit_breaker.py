"""Circuit breaker for LLM provider calls.

Prevents cascading failures by fast-failing when an upstream is down, instead
of exhausting retries on every request.

States:
- CLOSED: Normal operation, requests go through
- OPEN: The failure domain is down, requests fail immediately
- HALF_OPEN: Testing recovery with a single request

Failure domains (#1203). One process-global breaker is the wrong scope: a
burst of failures from one provider must not open the breaker for an unrelated
provider. Identity is the physical upstream, not the model string:

- ``provider:<id>`` — every model that routes to that provider shares one
  breaker. ``openai/gpt-4`` and ``openai/gpt-4o`` are the same domain.
- ``gateway`` — the shared gateway dependency. It opens only when the gateway
  itself is unreachable, and that higher-level breaker is allowed to block
  every provider that depends on it.

Dynamically discovered provider domains are capped
(``circuit_breaker_max_domains``). Closed idle domains are retired first; the
gateway breaker is never evicted. Domain keys are normalized provider ids,
never URLs or credentials.
"""

from __future__ import annotations

import asyncio
import math
import re
import threading
import time
from collections import OrderedDict, deque
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

    def reset(self) -> None:
        """Return this breaker to CLOSED and drop recorded failures.

        Domain retirement and tests use this. It is not an admission transition:
        callers that still hold a probe must treat the domain as gone.
        """
        with self._lock:
            self._clear_probe_locked()
            self._failures.clear()
            self._failure_count = 0
            self._last_failure_time = 0.0
            self._set_state_locked(CircuitState.CLOSED)


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open."""

    def __init__(self, breaker: CircuitBreaker) -> None:
        super().__init__(
            f"Circuit breaker '{breaker.name}' is open — "
            f"provider reached {breaker.failure_threshold} failures "
            f"within {breaker.failure_window:g}s"
        )


def circuit_breaker_from_settings(settings: Settings | None = None) -> CircuitBreaker:
    """Construct one LLM circuit from validated deployment policy."""
    effective = settings or get_settings()
    return CircuitBreaker(
        name="llm_provider",
        failure_threshold=effective.circuit_breaker_failure_threshold,
        recovery_timeout=effective.circuit_breaker_recovery_timeout_s,
    )


# Reviewed failure-domain ids. ``gateway`` is the shared dependency; a provider
# id is everything that can fail independently of other providers. Several model
# strings that name the same provider must not mint separate breakers.
SHARED_GATEWAY_DOMAIN = "gateway"
_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,62}")


def failure_domain(*, provider: str | None = None, model: str = "") -> str:
    """Return the breaker key for what can actually fail independently.

    Explicit provider metadata wins. Otherwise a LiteLLM-style ``provider/model``
    route contributes only its prefix, so every model behind that provider
    shares one breaker. A bare alias, a URL, or anything that could carry a
    credential stays on the shared gateway domain instead of becoming its own
    breaker.
    """
    raw = provider.strip() if provider else ""
    if not raw:
        head, sep, _tail = model.partition("/")
        if sep:
            raw = head.strip()
    if not raw or "://" in raw or "@" in raw or any(char.isspace() for char in raw):
        return SHARED_GATEWAY_DOMAIN
    normalized = raw.lower()
    if not _PROVIDER_ID.fullmatch(normalized):
        return SHARED_GATEWAY_DOMAIN
    return f"provider:{normalized}"


class LlmCircuitPool:
    """Bounded set of per-provider breakers plus the shared gateway breaker.

    The gateway breaker is permanent. Provider domains are created on demand
    and retired when idle-and-closed, or when a new domain would exceed
    ``max_domains``. Open domains are evicted only to enforce that hard cap.
    """

    def __init__(
        self,
        gateway: CircuitBreaker,
        *,
        max_domains: int,
        failure_threshold: int,
        recovery_timeout: float,
        idle_after_s: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if isinstance(max_domains, bool) or not isinstance(max_domains, int) or max_domains < 1:
            raise ValueError("max_domains must be a positive integer")
        self._gateway = gateway
        self._max_domains = max_domains
        self._failure_threshold = failure_threshold
        self._recovery_timeout = float(recovery_timeout)
        self._idle_after = self._recovery_timeout if idle_after_s is None else float(idle_after_s)
        self._clock = time.monotonic if clock is None else clock
        self._lock = threading.Lock()
        self._domains: OrderedDict[str, CircuitBreaker] = OrderedDict()
        self._last_used: dict[str, float] = {}

    @property
    def gateway(self) -> CircuitBreaker:
        return self._gateway

    @property
    def max_domains(self) -> int:
        return self._max_domains

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> LlmCircuitPool:
        effective = settings or get_settings()
        gateway = circuit_breaker_from_settings(effective)
        return cls(
            gateway,
            max_domains=effective.circuit_breaker_max_domains,
            failure_threshold=effective.circuit_breaker_failure_threshold,
            recovery_timeout=effective.circuit_breaker_recovery_timeout_s,
        )

    def breaker(self, domain: str) -> CircuitBreaker:
        """Return the breaker for ``domain``, creating a provider domain if needed."""
        if domain == SHARED_GATEWAY_DOMAIN:
            return self._gateway
        with self._lock:
            now = self._now()
            self._sweep_locked(now)
            found = self._domains.get(domain)
            if found is not None:
                self._domains.move_to_end(domain)
                self._last_used[domain] = now
                return found
            self._make_room_locked()
            created = CircuitBreaker(
                name=domain,
                failure_threshold=self._failure_threshold,
                recovery_timeout=self._recovery_timeout,
            )
            self._domains[domain] = created
            self._last_used[domain] = now
            return created

    def is_open(self, domain: str) -> bool:
        """Whether ``domain`` is OPEN. Does not create a breaker or take a probe."""
        if domain == SHARED_GATEWAY_DOMAIN:
            return self._gateway.state == CircuitState.OPEN
        with self._lock:
            breaker = self._domains.get(domain)
        if breaker is None:
            return False
        return breaker.state == CircuitState.OPEN

    def domains(self) -> tuple[str, ...]:
        """Provider domains currently retained, least-recently used first."""
        with self._lock:
            return tuple(self._domains)

    def nonclosed(self) -> tuple[tuple[str, str], ...]:
        """Provider domains that are open or half-open, in stable order.

        Values are state names (``open``, ``half_open``). The shared gateway is
        reported separately by :func:`llm_health_detail`. Keys are domain ids,
        never credentials.
        """
        with self._lock:
            items = tuple(self._domains.items())
        reported: list[tuple[str, str]] = []
        for domain, breaker in items:
            state = breaker.state
            if state is not CircuitState.CLOSED:
                reported.append((domain, state.value))
        reported.sort()
        return tuple(reported)

    def reset(self) -> None:
        """Drop provider domains and close the gateway breaker."""
        with self._lock:
            for domain in list(self._domains):
                self._drop_locked(domain)
        self._gateway.reset()

    def _now(self) -> float:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("clock must return a finite number")
        return float(value)

    def _sweep_locked(self, now: float) -> None:
        stale = [
            domain
            for domain, breaker in self._domains.items()
            if now - self._last_used.get(domain, now) >= self._idle_after
            and breaker.state == CircuitState.CLOSED
        ]
        for domain in stale:
            self._drop_locked(domain)

    def _make_room_locked(self) -> None:
        if len(self._domains) < self._max_domains:
            return
        closed = [
            domain
            for domain, breaker in self._domains.items()
            if breaker.state == CircuitState.CLOSED
        ]
        if closed:
            oldest_closed = min(closed, key=lambda domain: self._last_used.get(domain, 0.0))
            self._drop_locked(oldest_closed)
            return
        oldest = min(self._domains, key=lambda domain: self._last_used.get(domain, 0.0))
        logger.warning(
            "circuit_domain_evicted",
            domain=oldest,
            max_domains=self._max_domains,
        )
        self._drop_locked(oldest)

    def _drop_locked(self, domain: str) -> None:
        breaker = self._domains.pop(domain, None)
        self._last_used.pop(domain, None)
        if breaker is not None:
            # Publish closed so a retired domain is not stuck "open" in metrics.
            breaker.reset()


def domain_blocks_routing(domain: str) -> bool:
    """True when ``domain`` is OPEN.

    HALF_OPEN does not block routing: the call path must still be able to own
    that domain's single probe. Missing domains are not open.
    """
    return llm_breakers.is_open(domain)


def provider_blocks_routing(provider: str) -> bool:
    """True when this provider must not be selected.

    An open shared gateway blocks every provider that depends on it. An open
    provider blocks only its own domain. HALF_OPEN stays selectable so the
    call path can own the probe. Quota, Binding, and budget checks stay with
    the caller; this does not widen them.
    """
    if domain_blocks_routing(SHARED_GATEWAY_DOMAIN):
        return True
    return domain_blocks_routing(failure_domain(provider=provider))


def llm_health_detail() -> tuple[str, str]:
    """Gateway state plus any non-closed provider domain, with no credentials.

    The first element is the shared gateway state (``closed``, ``half_open``,
    or ``open``). The detail string names provider domains that are not closed
    so operators can see which failure domain is recovering.
    """
    state = llm_circuit.state.value
    parts = [f"circuit={state}"]
    parts.extend(f"{domain}={domain_state}" for domain, domain_state in llm_breakers.nonclosed())
    return state, "; ".join(parts)


# Shared gateway breaker, plus per-provider domains. Settings validation
# enforces the security floor before these values can become runtime behavior.
llm_breakers = LlmCircuitPool.from_settings()
llm_circuit = llm_breakers.gateway
