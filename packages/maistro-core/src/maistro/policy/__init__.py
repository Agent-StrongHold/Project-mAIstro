"""Stateful, sequence-aware policy engine (generalizes ADR-085 quota + ADR-086 events).

Decisions that depend on the sequence of actions under a scope — cumulative
budgets, after-N-of-a-kind approvals, forbidden orderings, velocity limits —
rather than one call in isolation. Ties into the harness ``ActionGate`` via
``PolicyActionGate`` (SPEC-208).
"""

from __future__ import annotations

from maistro.policy.engine import SequencePolicyEngine
from maistro.policy.gate import PolicyActionGate
from maistro.policy.rules import (
    AfterCountRule,
    BudgetRule,
    ForbiddenPairRule,
    PolicyRule,
    VelocityRule,
)
from maistro.policy.types import Action, Decision, PolicyVerdict, SequenceState

__all__ = [
    "Action",
    "AfterCountRule",
    "BudgetRule",
    "Decision",
    "ForbiddenPairRule",
    "PolicyActionGate",
    "PolicyRule",
    "PolicyVerdict",
    "SequencePolicyEngine",
    "SequenceState",
    "VelocityRule",
]
