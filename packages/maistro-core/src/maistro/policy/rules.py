"""Composable rules for the sequence-aware policy engine.

Each rule inspects the *prospective* state (running totals + history, already
advanced by the action under evaluation) and either returns a non-ALLOW verdict
to intervene or ``None`` to abstain. The engine combines rule outputs: any DENY
wins immediately; otherwise the first REQUIRE_APPROVAL stands (unless approved).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from maistro.policy.types import Action, Decision, PolicyVerdict, SequenceState


@runtime_checkable
class PolicyRule(Protocol):
    @property
    def name(self) -> str: ...

    def evaluate(self, action: Action, prospective: SequenceState) -> PolicyVerdict | None: ...


@dataclass(frozen=True)
class BudgetRule:
    """Cumulative cap on one dimension across the whole sequence (ADR-085 generalized)."""

    dimension: str  # "tokens" | "cost" | "seconds" | "count"
    limit: float
    decision: Decision = Decision.DENY

    @property
    def name(self) -> str:
        return f"budget:{self.dimension}<={self.limit}"

    def evaluate(self, action: Action, prospective: SequenceState) -> PolicyVerdict | None:
        value = float(getattr(prospective, self.dimension))
        if value > self.limit:
            return PolicyVerdict(
                self.decision,
                f"cumulative {self.dimension} {value:g} exceeds {self.limit:g}",
                self.name,
            )
        return None


@dataclass(frozen=True)
class AfterCountRule:
    """Once a kind has occurred more than ``threshold`` times, gate further ones."""

    kind: str
    threshold: int
    decision: Decision = Decision.REQUIRE_APPROVAL

    @property
    def name(self) -> str:
        return f"after_count:{self.kind}>{self.threshold}"

    def evaluate(self, action: Action, prospective: SequenceState) -> PolicyVerdict | None:
        seen = prospective.counts_by_kind.get(self.kind, 0)
        if action.kind == self.kind and seen > self.threshold:
            return PolicyVerdict(
                self.decision, f"{self.kind} occurred {seen}x (> {self.threshold})", self.name
            )
        return None


@dataclass(frozen=True)
class ForbiddenPairRule:
    """Gate an action of ``after`` kind when a ``before`` kind is already in history.

    E.g. require approval for a ``git_push`` that follows a ``credential_read``.
    """

    before: str
    after: str
    decision: Decision = Decision.REQUIRE_APPROVAL

    @property
    def name(self) -> str:
        return f"forbidden_pair:{self.before}->{self.after}"

    def evaluate(self, action: Action, prospective: SequenceState) -> PolicyVerdict | None:
        if action.kind != self.after:
            return None
        # Use the durable, unbounded counts_by_kind rather than the bounded
        # `history` deque: a `before` action that scrolled out of the recent
        # window (e.g. 256 unrelated actions after a credential_read) must still
        # gate — otherwise the ordering rule is bypassable by padding history.
        prior_before = prospective.counts_by_kind.get(self.before, 0)
        if self.before == self.after:
            prior_before -= 1  # the action under evaluation already incremented its own kind
        if prior_before > 0:
            return PolicyVerdict(self.decision, f"{self.after} follows {self.before}", self.name)
        return None


@dataclass(frozen=True)
class VelocityRule:
    """Deny more than ``max_in_window`` actions of a kind within the last ``window`` actions."""

    kind: str
    max_in_window: int
    window: int
    decision: Decision = Decision.DENY

    @property
    def name(self) -> str:
        return f"velocity:{self.kind}<={self.max_in_window}/{self.window}"

    def evaluate(self, action: Action, prospective: SequenceState) -> PolicyVerdict | None:
        if action.kind != self.kind:
            return None
        recent = list(prospective.history)[-self.window :]
        n = sum(1 for a in recent if a.kind == self.kind)
        if n > self.max_in_window:
            return PolicyVerdict(
                self.decision,
                f"{n} {self.kind} in last {self.window} actions (> {self.max_in_window})",
                self.name,
            )
        return None
