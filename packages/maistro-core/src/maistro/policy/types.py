"""Types for the stateful, sequence-aware policy engine.

Generalizes ADR-085 (quota: cumulative token budgets) and ADR-086 (events) into
one primitive: policy decisions that depend on the *sequence* of actions taken so
far under a scope (a session, an agent, a harness run), not just the current call.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class Action:
    """One unit of work in a sequence — a harness turn, a tool call, an API request."""

    kind: str
    tokens: int = 0
    cost: float = 0.0
    seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyVerdict:
    decision: Decision
    reason: str = ""
    rule: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


def _new_history() -> deque[Action]:
    return deque(maxlen=256)


@dataclass
class SequenceState:
    """Running totals + bounded recent history for one policy key."""

    tokens: int = 0
    cost: float = 0.0
    seconds: float = 0.0
    count: int = 0
    counts_by_kind: dict[str, int] = field(default_factory=dict)
    history: deque[Action] = field(default_factory=_new_history)

    @classmethod
    def empty(cls, history_limit: int = 256) -> SequenceState:
        return cls(history=deque(maxlen=history_limit))

    def with_action(self, action: Action) -> SequenceState:
        """Return a copy advanced by ``action`` — prospective, not committed."""
        counts = dict(self.counts_by_kind)
        counts[action.kind] = counts.get(action.kind, 0) + 1
        hist: deque[Action] = deque(self.history, maxlen=self.history.maxlen)
        hist.append(action)
        return SequenceState(
            tokens=self.tokens + action.tokens,
            cost=self.cost + action.cost,
            seconds=self.seconds + action.seconds,
            count=self.count + 1,
            counts_by_kind=counts,
            history=hist,
        )

    def commit(self, action: Action) -> None:
        """Advance this state in place (the action actually happened)."""
        self.tokens += action.tokens
        self.cost += action.cost
        self.seconds += action.seconds
        self.count += 1
        self.counts_by_kind[action.kind] = self.counts_by_kind.get(action.kind, 0) + 1
        self.history.append(action)

    def copy(self) -> SequenceState:
        """Return a detached deep-ish copy — mutating it can't affect the source
        (``counts_by_kind`` and ``history`` are fresh containers)."""
        return SequenceState(
            tokens=self.tokens,
            cost=self.cost,
            seconds=self.seconds,
            count=self.count,
            counts_by_kind=dict(self.counts_by_kind),
            history=deque(self.history, maxlen=self.history.maxlen),
        )
