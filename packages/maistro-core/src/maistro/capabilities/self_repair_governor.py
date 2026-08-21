"""Safety governor for the self_repair loop (SPEC-188).

An autonomous actuator that restarts infrastructure must be self-limiting. The
governor gates every actionable proposal before it is dispatched:

- in-flight guard — never two actions for one resource at once;
- attempt budget — at most N dispatches per resource per rolling window;
- cooldown + exponential backoff — wait after acting; back off on repeated failure;
- flap detection — stop auto-remediating a resource that oscillates recover↔fail.

State is per-resource and in-memory (v1). The clock is injectable for tests. The
exponential cooldown mirrors the ADR-038 backoff shape, minus jitter — a control
loop wants deterministic, predictable timing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class GovernorReason(StrEnum):
    OK = "ok"
    IN_FLIGHT = "in_flight"
    COOLDOWN = "cooldown"
    BUDGET = "budget"
    FLAP = "flap"


@dataclass(frozen=True)
class GovernorDecision:
    allowed: bool
    reason: GovernorReason


@dataclass
class _ResourceState:
    attempts: list[float] = field(
        default_factory=list
    )  # dispatch timestamps (for the window budget)
    last_dispatch: float | None = None
    in_flight: bool = False
    consecutive_failures: int = 0
    recovered_flag: bool = False  # recovered since its last dispatch
    flap_count: int = 0  # times re-dispatched after a recovery (oscillation)


class SafetyGovernor:
    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        budget: int = 3,
        window_s: float = 1800.0,
        cooldown_s: float = 60.0,
        flap_threshold: int = 3,
        backoff_cap: int = 4,
    ) -> None:
        self._clock = clock or time.monotonic
        self._budget = budget
        self._window_s = window_s
        self._cooldown_s = cooldown_s
        self._flap_threshold = flap_threshold
        self._backoff_cap = backoff_cap
        self._state: dict[str, _ResourceState] = {}

    def _st(self, resource: str) -> _ResourceState:
        return self._state.setdefault(resource, _ResourceState())

    def _effective_cooldown(self, st: _ResourceState) -> float:
        # base * 2**failures, capped — deterministic exponential backoff (ADR-038 shape).
        return self._cooldown_s * (2.0 ** min(st.consecutive_failures, self._backoff_cap))

    def allow(self, resource: str) -> GovernorDecision:
        st = self._st(resource)
        now = self._clock()

        if st.in_flight:
            return GovernorDecision(False, GovernorReason.IN_FLIGHT)

        if st.flap_count >= self._flap_threshold:
            return GovernorDecision(False, GovernorReason.FLAP)

        # Prune attempts outside the rolling window before checking the budget.
        st.attempts = [t for t in st.attempts if now - t < self._window_s]
        if len(st.attempts) >= self._budget:
            return GovernorDecision(False, GovernorReason.BUDGET)

        if st.last_dispatch is not None and now - st.last_dispatch < self._effective_cooldown(st):
            return GovernorDecision(False, GovernorReason.COOLDOWN)

        return GovernorDecision(True, GovernorReason.OK)

    def record_dispatch(self, resource: str) -> None:
        st = self._st(resource)
        now = self._clock()
        if st.recovered_flag:
            # We fixed it before, it broke again → an oscillation.
            st.flap_count += 1
            st.recovered_flag = False
        st.attempts.append(now)
        st.last_dispatch = now
        st.in_flight = True

    def record_result(self, resource: str, *, recovered: bool) -> None:
        st = self._st(resource)
        st.in_flight = False
        if recovered:
            st.recovered_flag = True
            st.consecutive_failures = 0
        else:
            st.consecutive_failures += 1

    def state_summary(self) -> dict[str, dict[str, object]]:
        """Introspection for the API/UI — current per-resource governor state."""
        return {
            r: {
                "attempts_in_window": len(s.attempts),
                "in_flight": s.in_flight,
                "consecutive_failures": s.consecutive_failures,
                "flap_count": s.flap_count,
            }
            for r, s in self._state.items()
        }
