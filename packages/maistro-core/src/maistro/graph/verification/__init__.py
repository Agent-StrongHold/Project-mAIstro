"""Verification-aware execution and adaptive routing (epic M4-I).

Three primitives, all consumed by the canonical durable executor's
authoritative fold:

- :mod:`.taxonomy` — actionable/transitional/terminal classification of
  successful tool results.
- :mod:`.expectations` — the plan queue: per-node predicted post-states,
  supervised on completion, halting the Run on mismatch instead of routing
  a contradicted plan onward.
- :mod:`.escalation` — cheap-first, quality-triggered model escalation: a
  completed visit below its quality floor is withheld and re-queued at the
  next ladder rung, within the node's existing visit budget.
- :mod:`.routing` — text-vs-image observation modality routing and
  model-aware content-part encoding.

Everything here rides the immutable Graph snapshot (node policies) and
GraphExecutionState metadata; nothing introduces a second execution
authority. Goal -> Graph -> Run -> NodeRun -> Attempt remains the only
lifecycle.
"""

from __future__ import annotations

from .escalation import (
    ESCALATED_MODEL_CONTEXT_KEY,
    ESCALATION_LADDER_POLICY_KEY,
    ESCALATION_STATE_METADATA_KEY,
    LADDER_START_CONTEXT_KEY,
    QUALITY_METADATA_KEY,
    EscalationDecision,
    ModelLadder,
    QualityGate,
    decide_escalation,
    escalation_from_policy,
)
from .expectations import (
    EXPECT_POST_STATE_POLICY_KEY,
    ExpectationVerdict,
    ExpectationViolation,
    PlanExpectationQueue,
    PostStateExpectation,
    expectation_from_policy,
)
from .quality import summarize_quality
from .routing import (
    ObservationModality,
    ObservationRoute,
    classify_observation,
    encode_observation,
    route_observation,
    route_observations,
)
from .taxonomy import (
    RESULT_STATE_METADATA_KEY,
    ResultState,
    classify_result_state,
)

__all__ = [
    "ESCALATED_MODEL_CONTEXT_KEY",
    "ESCALATION_LADDER_POLICY_KEY",
    "ESCALATION_STATE_METADATA_KEY",
    "EXPECT_POST_STATE_POLICY_KEY",
    "LADDER_START_CONTEXT_KEY",
    "QUALITY_METADATA_KEY",
    "RESULT_STATE_METADATA_KEY",
    "EscalationDecision",
    "ExpectationVerdict",
    "ExpectationViolation",
    "ModelLadder",
    "ObservationModality",
    "ObservationRoute",
    "PlanExpectationQueue",
    "PostStateExpectation",
    "QualityGate",
    "ResultState",
    "classify_observation",
    "classify_result_state",
    "decide_escalation",
    "encode_observation",
    "escalation_from_policy",
    "expectation_from_policy",
    "route_observation",
    "route_observations",
    "summarize_quality",
]
