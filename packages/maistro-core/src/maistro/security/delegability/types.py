"""Types for agent-facing delegability decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from maistro.security.sentinel.authz_types import AuthzDecision

Reversibility = Literal["internal", "reversible", "irreversible"]
DelegabilityStatus = Literal[
    "delegable",
    "partially_delegable",
    "not_yet_delegable",
    "blocked",
]


@dataclass(frozen=True)
class ProposedAction:
    """An action an agent wants to take at a trust boundary."""

    name: str
    reversibility: Reversibility = "reversible"
    args: dict[str, object] = field(default_factory=dict)
    impacts: tuple[str, ...] = ()
    safe_subactions: tuple[str, ...] = ()
    missing_policy: tuple[str, ...] = ()


@dataclass(frozen=True)
class DelegabilityContext:
    """Execution context that can affect whether an action is delegable."""

    within_budget: bool = True
    rlphd_features: dict[str, float] | None = None


@dataclass(frozen=True)
class DelegabilityDecision:
    """Structured answer for agents and UIs before an action executes."""

    action: str
    status: DelegabilityStatus
    authz: AuthzDecision
    reasons: tuple[str, ...] = ()
    missing_policy: tuple[str, ...] = ()
    unlock_requirements: tuple[str, ...] = ()
    safe_subactions: tuple[str, ...] = ()
    reversibility: Reversibility = "reversible"
    confidence: float | None = None

    @property
    def can_execute(self) -> bool:
        return self.status == "delegable"
