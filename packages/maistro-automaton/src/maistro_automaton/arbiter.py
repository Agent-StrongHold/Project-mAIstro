"""Producers and the motivation arbiter: how pressure becomes one action.

A producer is a threshold-gated candidate generator: it owns a drive, stays
silent while pressure is under its threshold, and submits Candidates when it
isn't. The arbiter is the counterweight — at most ONE action fires per tick,
highest drive wins, and a refractory period keeps a recently-fired (or
recently-refused) action key from re-firing on the next tick.

The refractory period is the anti-churn mechanism. Without it, an actor whose
action was refused re-submits identical pressure every tick forever: eighteen
enqueues against the same wedge, each surprise, each refused. With it, the
first refusal scars the action key for a cooldown the host sizes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from maistro_automaton.types import Candidate


@runtime_checkable
class Producer(Protocol):
    """Generates Candidates when its drives say so; silent otherwise."""

    name: str

    def should_fire(self, drive_levels: Mapping[str, float]) -> bool: ...

    def submit(self, drive_levels: Mapping[str, float]) -> Candidate | None: ...


@dataclass(frozen=True)
class ThresholdGate:
    """Fire only when a named drive crosses a named threshold.

    The default posture of an automaton is silence; a ThresholdGate is the
    explicit, inspectable statement of what it takes to break that silence.
    """

    drive: str
    threshold: float

    def passes(self, drive_levels: Mapping[str, float]) -> bool:
        return drive_levels.get(self.drive, 0.0) >= self.threshold


@dataclass
class MotivationArbiter:
    """One action per tick: highest-drive candidate not in refractory.

    Candidates persist across ticks until fired or superseded by a newer
    Candidate with the same key (latest pressure wins — an actor's attention
    is its most recent read of the world). Firing an action key starts its
    refractory cooldown; submissions during cooldown replace the parked
    payload but stay unfireable until the clock clears.
    """

    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    refractory: dict[str, timedelta] = field(default_factory=dict)
    _parked: dict[str, Candidate] = field(default_factory=dict)
    _fired_at: dict[str, datetime] = field(default_factory=dict)

    def submit(self, candidate: Candidate) -> None:
        self._parked[candidate.key] = candidate

    def tick(self) -> Candidate | None:
        """Fire at most one candidate; returns it, or None (silence is legal)."""
        now = self.clock()
        fireable = [
            c
            for c in self._parked.values()
            if (until := self._fired_at.get(c.key)) is None
            or now - until >= self.refractory.get(c.key, timedelta(0))
        ]
        if not fireable:
            return None
        winner = max(fireable, key=lambda c: c.drive_score)
        self._parked.pop(winner.key)
        self._fired_at[winner.key] = now
        return winner

    def park_count(self) -> int:
        return len(self._parked)

    def in_refractory(self, key: str) -> bool:
        until = self._fired_at.get(key)
        if until is None:
            return False
        return (self.clock() - until) < self.refractory.get(key, timedelta(0))


def candidate(
    key: str, producer: str, drive: str, drive_score: float, payload: Any = None
) -> Candidate:
    """Convenience constructor for hosts that build candidates inline."""
    return Candidate(
        key=key,
        producer=producer,
        drive=drive,
        drive_score=drive_score,
        payload=payload,
    )
