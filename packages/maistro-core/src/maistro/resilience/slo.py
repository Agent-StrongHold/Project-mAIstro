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
        if not 0.0 < self.target < 1.0:
            raise ValueError("target must be a ratio strictly between 0 and 1")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

    @property
    def total_budget_seconds(self) -> float:
        """Downtime the target tolerates across one full compliance window."""
        return (1.0 - self.target) * self.window_seconds


class ErrorBudget:
    """Tracks downtime against one SLO's budget over its rolling window.

    Every mutating or measuring call accepts an explicit ``now`` so budget
    math is deterministic under test; production callers omit it and get the
    monotonic clock.
    """

    def __init__(self, definition: SloDefinition) -> None:
        self.definition = definition
        self._downtime: deque[tuple[float, float]] = deque()

    def _resolve_now(self, now: float | None) -> float:
        return time.monotonic() if now is None else now

    def _prune(self, now: float) -> None:
        horizon = now - self.definition.window_seconds
        while self._downtime and self._downtime[0][0] <= horizon:
            self._downtime.popleft()

    def record_downtime(self, seconds: float, *, now: float | None = None) -> None:
        """Charge unavailability against the budget and republish the gauge."""
        if seconds < 0:
            raise ValueError("downtime seconds cannot be negative")
        resolved = self._resolve_now(now)
        if seconds:
            self._downtime.append((resolved, seconds))
        self.publish(now=resolved)

    def consumed_seconds(self, *, now: float | None = None) -> float:
        resolved = self._resolve_now(now)
        self._prune(resolved)
        return sum(seconds for _, seconds in self._downtime)

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

        The steady allowance for a lookback is the fraction of the total
        budget that an exactly-on-target service would spend in that time:
        ``total_budget * lookback / window``.
        """
        if lookback_seconds <= 0:
            raise ValueError("lookback_seconds must be positive")
        resolved = self._resolve_now(now)
        self._prune(resolved)
        horizon = resolved - lookback_seconds
        consumed = sum(seconds for at, seconds in self._downtime if at > horizon)
        allowance = self.definition.total_budget_seconds * (
            lookback_seconds / self.definition.window_seconds
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
