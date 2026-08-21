"""Delegability evaluation primitives.

This package turns Sentinel's authorization answer into an agent-facing
"what can I safely do now, and what would unlock the rest?" decision.
"""

from maistro.security.delegability.evaluator import evaluate_delegability
from maistro.security.delegability.types import (
    DelegabilityContext,
    DelegabilityDecision,
    DelegabilityStatus,
    ProposedAction,
    Reversibility,
)

__all__ = [
    "DelegabilityContext",
    "DelegabilityDecision",
    "DelegabilityStatus",
    "ProposedAction",
    "Reversibility",
    "evaluate_delegability",
]
