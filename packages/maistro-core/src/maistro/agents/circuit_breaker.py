"""Circuit breakers for LLM provider calls, scoped by failure domain.

Prevents cascading failures by fast-failing when an LLM dependency
is down, instead of exhausting retries on every request.

Breaker scope (#1203, ADR-038 "per upstream dependency"): state is keyed to
what can actually fail independently — one gateway endpoint x one upstream
routing target — never to one process-global flag. A flaky provider opens its
own breaker only; unrelated providers keep flowing. The gateway itself is an
explicit shared dependency with its own breaker: when it fails, the
gateway-level breaker intentionally represents that shared failure for every
provider behind it.

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
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import Any
from urllib.parse import urlparse

import structlog

from maistro.config.settings import Settings, get_settings
from maistro.observability.metrics import maistro_circuit_state
from maistro.security.resource_policy import (
    BASELINE_CIRCUIT_FAILURE_THRESHOLD,
    BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
    MAX_CIRCUIT_DOMAINS,
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


# --- Failure-domain scoping (#1203) ------------------------------------------

#: Sentinel provider slot for a gateway's own breaker: the shared dependency
#: every provider behind that endpoint depends on. Never a real routing target.
GATEWAY_PROVIDER = "(gateway)"

_DEFAULT_MAX_DOMAINS = 64


def sanitize_endpoint(url: str | None) -> str:
    """Reduce a gateway base_url to its host:port for breaker identity.

    Breaker names reach logs, metrics labels and health payloads, so the
    identity carries no scheme, path, query, or userinfo — credentials can
    never leak through a failure-domain name.
    """
    if not url or not url.strip():
        return "direct"
    candidate = url.strip()
    if "//" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = parsed.hostname or "unknown"
    try:
        port = parsed.port
    except ValueError:
        port = None
    return host if port is None else f"{host}:{port}"


#: First path segment of these LiteLLM-style prefixes names the physical
#: upstream; for multi-vendor aggregators the *second* segment does.
_VENDOR_ROUTED_PREFIXES = frozenset({"openrouter"})


def routing_provider(model: str) -> str:
    """Derive the upstream routing target from a gateway model string.

    ``anthropic/claude-3-opus`` → ``anthropic``; ``openrouter/google/gemini``
    → ``openrouter/google`` (the vendor is what fails independently behind an
    aggregator). A bare alias with no routing segment is isolated under its
    own name: with no routing metadata the engine cannot know two aliases
    share an upstream, and under-grouping is the dangerous direction —
    callers that know better pass an explicit ``provider=`` instead.
    """
    text = model.strip().removeprefix("openai:")
    parts = [part for part in text.split("/") if part]
    if not parts:
        return "unknown"
    if len(parts) == 1:
        return parts[0]
    head = parts[0].lower()
    if head in _VENDOR_ROUTED_PREFIXES:
        return f"{head}/{parts[1].lower()}"
    return head


@dataclass(frozen=True)
class FailureDomain:
    """One independently-failing LLM dependency (ADR-038).

    ``gateway`` is the sanitized endpoint the call traverses; ``provider`` is
    the upstream routing target behind it. Two models that share both share a
    physical failure domain and one breaker; models on different providers —
    or on different gateways — never share one.
    """

    gateway: str
    provider: str

    def key(self) -> str:
        return f"{self.gateway}|{self.provider}"

    def __str__(self) -> str:
        return f"gw={self.gateway};provider={self.provider}"


def resolve_failure_domain(
    model: str,
    base_url: str | None = None,
    provider: str | None = None,
) -> FailureDomain:
    """Resolve the failure domain one LLM call depends on.

    ``provider`` overrides the model-string derivation when the caller has
    reviewed grouping knowledge (e.g. registry ``ModelMetadata.provider``).
    """
    target = (provider or "").strip() or routing_provider(model)
    return FailureDomain(gateway=sanitize_endpoint(base_url), provider=target)


class DomainCircuitBank:
    """Bounded, thread-safe registry of per-failure-domain circuit breakers.

    Each domain gets its own :class:`CircuitBreaker`, so HALF_OPEN probe
    ownership is concurrency-safe per domain by construction — a probe leased
    in one domain never gates another. Admission is hierarchical: the
    gateway-level breaker is consulted first, then the provider's. Only an
    explicitly shared failure (gateway unreachable) records into the
    gateway-level breaker; provider-scoped failures never cross domains.

    Cardinality is bounded by ``max_domains`` for dynamically discovered
    providers: when full, the least-recently-used CLOSED domain is evicted;
    if every tracked domain is open or probing, the least-recently-used one
    is evicted with a warning so a newly discovered provider can still be
    admitted (it re-opens on its own failures).
    """

    def __init__(
        self,
        failure_threshold: int = BASELINE_CIRCUIT_FAILURE_THRESHOLD,
        recovery_timeout: float = BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
        max_domains: int = _DEFAULT_MAX_DOMAINS,
        name_prefix: str = "llm",
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if (
            isinstance(max_domains, bool)
            or not isinstance(max_domains, int)
            or not 0 < max_domains <= MAX_CIRCUIT_DOMAINS
        ):
            raise ValueError(f"max_domains must be a positive integer <= {MAX_CIRCUIT_DOMAINS}")
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.max_domains = max_domains
        self.name_prefix = name_prefix
        self._clock = clock
        self._lock = threading.Lock()
        self._domains: OrderedDict[str, tuple[FailureDomain, CircuitBreaker]] = OrderedDict()

    def _gateway_domain(self, domain: FailureDomain) -> FailureDomain:
        return FailureDomain(gateway=domain.gateway, provider=GATEWAY_PROVIDER)

    def _breaker_for(self, domain: FailureDomain) -> CircuitBreaker:
        key = domain.key()
        with self._lock:
            existing = self._domains.get(key)
            if existing is not None:
                self._domains.move_to_end(key)
                return existing[1]
            while len(self._domains) >= self.max_domains:
                self._evict_locked()
            breaker = CircuitBreaker(
                failure_threshold=self.failure_threshold,
                recovery_timeout=self.recovery_timeout,
                name=f"{self.name_prefix}:{domain}",
                clock=self._clock,
            )
            self._domains[key] = (domain, breaker)
            return breaker

    def _evict_locked(self) -> None:
        # Least-recently-used first; prefer a domain that is merely closed so
        # an open domain's protective state survives as long as possible.
        for key, (_, breaker) in self._domains.items():
            if breaker.state is CircuitState.CLOSED:
                del self._domains[key]
                logger.info("circuit_domain_evicted", name=breaker.name, reason="capacity")
                return
        key, (_, breaker) = self._domains.popitem(last=False)
        logger.warning(
            "circuit_domain_evicted_active",
            name=breaker.name,
            state=breaker.state.value,
            reason="capacity_no_closed_domain",
        )

    def breaker(self, domain: FailureDomain) -> CircuitBreaker:
        """The provider-level breaker for ``domain`` (created on first use)."""
        return self._breaker_for(domain)

    def admit(self, domain: FailureDomain) -> bool:
        """Atomically admit one call to ``domain`` or claim its recovery probe."""
        gateway = self._breaker_for(self._gateway_domain(domain))
        if not gateway.allow_request():
            return False
        provider = self._breaker_for(domain)
        if not provider.allow_request():
            # This caller will not reach the gateway after all — hand the
            # possibly-claimed recovery probe back instead of parking it.
            gateway.release_probe()
            return False
        return True

    def blocking_breaker(self, domain: FailureDomain) -> CircuitBreaker | None:
        """Diagnostic: which breaker currently blocks ``domain`` (gateway first).

        Pure state inspection — unlike :meth:`admit`, this claims no probe.
        """
        gateway = self.breaker(self._gateway_domain(domain))
        if gateway.state is not CircuitState.CLOSED:
            return gateway
        provider = self.breaker(domain)
        if provider.state is not CircuitState.CLOSED:
            return provider
        return None

    def record_success(self, domain: FailureDomain) -> None:
        """Record one successful call through gateway and provider alike."""
        self._breaker_for(self._gateway_domain(domain)).record_success()
        self._breaker_for(domain).record_success()

    def record_failure(self, domain: FailureDomain, *, shared: bool = False) -> None:
        """Record one failed call.

        ``shared=True`` means the shared gateway dependency itself failed
        (e.g. the endpoint refused the connection) — the gateway-level
        breaker intentionally represents that for every provider behind it.
        Provider-scoped failures never touch other domains' breakers.
        """
        if shared:
            self._breaker_for(self._gateway_domain(domain)).record_failure()
            return
        self._breaker_for(domain).record_failure()

    def snapshot(self) -> list[dict[str, str]]:
        """Per-domain state for health/metrics — names carry no credentials.

        Includes each gateway's own breaker under the ``(gateway)`` provider
        slot: a shared-endpoint outage blocks every provider behind it, so
        health must be able to name it rather than report every provider row
        closed while traffic is refused.
        """
        with self._lock:
            domains = list(self._domains.items())
        rows = [
            {
                "name": breaker.name,
                "gateway": domain.gateway,
                "provider": domain.provider,
                "state": breaker.state.value,
            }
            for _, (domain, breaker) in domains
        ]
        return sorted(rows, key=lambda row: row["name"])

    def reset(self) -> None:
        """Drop every tracked domain (administrative/test lifecycle hook)."""
        with self._lock:
            self._domains.clear()


def domain_bank_from_settings(settings: Settings | None = None) -> DomainCircuitBank:
    """Construct the process LLM circuit bank from validated deployment policy."""
    effective = settings or get_settings()
    return DomainCircuitBank(
        failure_threshold=effective.circuit_breaker_failure_threshold,
        recovery_timeout=effective.circuit_breaker_recovery_timeout_s,
        max_domains=effective.circuit_breaker_max_domains,
    )


# Global failure-domain-scoped circuit bank for LLM calls. Settings validation
# enforces the security floor and the cardinality bound before these values
# can become runtime behavior.
llm_circuits = domain_bank_from_settings()
