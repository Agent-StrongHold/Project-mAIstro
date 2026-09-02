"""Error budgets and SLO burn rate (ADR-038 §4).

An SLO names a target availability over a rolling compliance window; the
error budget is the unavailability that target tolerates. Burn rate compares
how fast the budget is being consumed over a lookback against the steady
rate that would exactly exhaust it at the window's end — burn rate 1.0 means
"on track to spend the whole budget, no more", and ADR-038's throttle signal
fires when the rate exceeds 2.0 sustained over one hour.

Reliability declares ``maistro_slo_remaining_budget_seconds`` per
``(service_key, slo)`` to the ADR-037 observability substrate: ADR-037 owns
the naming/registry contract, this module owns the metric's meaning.

The gauge is refreshed whenever downtime is recorded and whenever
``should_throttle`` is evaluated. Since recovery is time-driven rather than
event-driven, a consumer that only records downtime must call
``should_throttle`` (or ``publish``) on a periodic cadence, or the gauge will
lag the budget it reports.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Final

from maistro.observability.metrics import registry

DEFAULT_WINDOW_SECONDS: Final = 30 * 24 * 3600.0
THROTTLE_BURN_RATE: Final = 2.0
THROTTLE_LOOKBACK_SECONDS: Final = 3600.0

maistro_slo_remaining_budget_seconds = registry.gauge(
    "maistro_slo_remaining_budget_seconds",
    "Unspent error budget per SLO (ADR-038; labels: service_key, slo)",
)


@dataclass(frozen=True, slots=True)
class _DowntimeInterval:
    """One completed outage interval and its exact recorded duration."""

    start: float
    end: float
    seconds: float

    def overlap_seconds(self, *, start: float, end: float) -> float:
        """Return this interval's overlap with ``[start, end)`` at most once."""
        if self.end <= start:
            return 0.0
        if start <= self.start and self.end <= end:
            return self.seconds
        if self.start >= end:
            return 0.0
        overlap = min(self.end, end) - max(self.start, start)
        return min(self.seconds, max(0.0, overlap))


@dataclass(frozen=True)
class SloDefinition:
    """One service-level objective: a target over a rolling window.

    Per ADR-038, the numbers themselves are product decisions — this type
    carries whatever a product ROADMAP declares.
    """

    service_key: str
    slo: str
    target: float
    window_seconds: float = DEFAULT_WINDOW_SECONDS

    def __post_init__(self) -> None:
        if not math.isfinite(self.target) or not 0.0 < self.target < 1.0:
            raise ValueError("target must be a ratio strictly between 0 and 1")
        if not math.isfinite(self.window_seconds) or self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive and finite")

    @property
    def total_budget_seconds(self) -> float:
        """Downtime the target tolerates across one full compliance window."""
        return (1.0 - self.target) * self.window_seconds


class ErrorBudget:
    """Tracks downtime against one SLO's budget over its rolling window.

    ``record_downtime(seconds, now=t)`` treats ``t`` as the interval end and
    records the completed interval ``[t - seconds, t)``. Measurements charge
    only the interval portion overlapping their rolling window.

    Every mutating or measuring call accepts an explicit ``now`` so budget
    math is deterministic under test; production callers omit it and get the
    monotonic clock.
    """

    def __init__(self, definition: SloDefinition) -> None:
        self.definition = definition
        self._downtime: deque[_DowntimeInterval] = deque()

    def _resolve_now(self, now: float | None) -> float:
        resolved = time.monotonic() if now is None else now
        if not math.isfinite(resolved) or resolved < 0:
            raise ValueError("now must be non-negative and finite")
        return resolved

    def _prune(self, now: float) -> None:
        horizon = now - self.definition.window_seconds
        self._downtime = deque(interval for interval in self._downtime if interval.end > horizon)

    def _consumed_between(self, *, start: float, end: float) -> float:
        return sum(interval.overlap_seconds(start=start, end=end) for interval in self._downtime)

    def record_downtime(self, seconds: float, *, now: float | None = None) -> None:
        """Record ``seconds`` ending at ``now`` and republish the gauge."""
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("downtime seconds must be non-negative and finite")
        resolved = self._resolve_now(now)
        if seconds:
            start = resolved - seconds
            self._downtime.append(_DowntimeInterval(start=start, end=resolved, seconds=seconds))
        self.publish(now=resolved)

    def consumed_seconds(self, *, now: float | None = None) -> float:
        resolved = self._resolve_now(now)
        self._prune(resolved)
        return self._consumed_between(
            start=resolved - self.definition.window_seconds,
            end=resolved,
        )

    def remaining_seconds(self, *, now: float | None = None) -> float:
        return max(
            0.0,
            self.definition.total_budget_seconds - self.consumed_seconds(now=now),
        )

    def burn_rate(
        self,
        *,
        lookback_seconds: float = THROTTLE_LOOKBACK_SECONDS,
        now: float | None = None,
    ) -> float:
        """Budget consumed in the lookback, relative to the steady allowance.

        The effective lookback is the requested lookback capped at the
        compliance window. Its steady allowance is the fraction of the total
        budget that an exactly-on-target service would spend in that time:
        ``total_budget * effective_lookback / window``. The same effective
        lookback bounds interval overlap, so a longer request cannot dilute
        the burn rate with time outside the compliance window.
        """
        if not math.isfinite(lookback_seconds) or lookback_seconds <= 0:
            raise ValueError("lookback_seconds must be positive and finite")
        resolved = self._resolve_now(now)
        self._prune(resolved)
        effective_lookback_seconds = min(
            lookback_seconds,
            self.definition.window_seconds,
        )
        horizon = resolved - effective_lookback_seconds
        consumed = self._consumed_between(start=horizon, end=resolved)
        allowance = self.definition.total_budget_seconds * (
            effective_lookback_seconds / self.definition.window_seconds
        )
        if allowance == 0:
            return float("inf") if consumed else 0.0
        return consumed / allowance

    def should_throttle(
        self,
        *,
        threshold: float = THROTTLE_BURN_RATE,
        lookback_seconds: float = THROTTLE_LOOKBACK_SECONDS,
        now: float | None = None,
    ) -> bool:
        """ADR-038's throttle signal: burn rate above 2x sustained over 1h.

        The orchestrator defers non-critical work while this holds; the
        router's scarcity input (ADR-007) is the intended consumer.

        This is the periodic caller, so it also republishes the gauge. Budget
        recovery is time-driven — downtime ages out of the rolling window with
        no new event to record — so a gauge written only on `record_downtime`
        would sit at its depleted value indefinitely after a service recovered,
        and dashboards would report an exhaustion that had already healed.
        """
        resolved = self._resolve_now(now)
        throttling = self.burn_rate(lookback_seconds=lookback_seconds, now=resolved) > threshold
        self.publish(now=resolved)
        return throttling

    def publish(self, *, now: float | None = None) -> float:
        """Set the ADR-037 gauge to the current remaining budget; returns it."""
        remaining = self.remaining_seconds(now=now)
        maistro_slo_remaining_budget_seconds.set(
            remaining,
            service_key=self.definition.service_key,
            slo=self.definition.slo,
        )
        return remaining


__all__ = [
    "DEFAULT_WINDOW_SECONDS",
    "THROTTLE_BURN_RATE",
    "THROTTLE_LOOKBACK_SECONDS",
    "ErrorBudget",
    "SloDefinition",
    "maistro_slo_remaining_budget_seconds",
]
