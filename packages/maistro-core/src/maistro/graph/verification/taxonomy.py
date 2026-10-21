"""Tool-result state taxonomy for verification-aware execution (epic M4-I).

Every successful tool/LLM/transform result moves the world somewhere, and a
supervisor that cannot say *where* cannot notice when the world moved the
wrong way. This module gives every successful :class:`NodeResult` exactly one
of three states:

- ``ACTIONABLE`` — the result hands the next move to an external actor (a
  person or a peer agent). Work inside this Run is blocked on them.
- ``TRANSITIONAL`` — the result moved state forward but the goal is not yet
  satisfied; more in-graph work follows.
- ``TERMINAL`` — the result satisfies the goal; nothing is owed.

Failures are deliberately outside this taxonomy: a failed result has no
post-state to classify, and `error_code`/`error_message` already say what
happened. ``classify_result_state`` returns ``None`` for them instead of
inventing a state that would let a supervisor reason about a world that does
not exist.

Classification is deterministic and ordered. An explicit ``result_state``
metadata override written by the node wins; a value that is not one of the
three states raises rather than silently degrading — a typo in node code is
a bug to surface, not a default to absorb.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from maistro.graph.nodes.base import HUMAN_PAUSE_REASONS, NodeResult


class ResultState(StrEnum):
    """Where a successful result leaves the world, from the Run's perspective."""

    ACTIONABLE = "actionable"
    TRANSITIONAL = "transitional"
    TERMINAL = "terminal"


#: NodeResult metadata key a node sets to declare its own state explicitly.
RESULT_STATE_METADATA_KEY = "result_state"
#: Metadata key declaring the goal is satisfied (truthy => TERMINAL).
GOAL_SATISFIED_METADATA_KEY = "goal_satisfied"
#: Metadata key declaring an external actor must act next (truthy => ACTIONABLE).
REQUIRES_ACTOR_ACTION_METADATA_KEY = "requires_actor_action"


def classify_result_state(result: NodeResult) -> ResultState | None:
    """Classify one successful NodeResult, or ``None`` when it failed.

    Order is the contract:

    1. Failed results return ``None`` — no post-state exists to classify.
    2. An explicit ``result_state`` metadata override wins; an unknown value
       raises ``ValueError`` so the misclassified world is loud.
    3. A human-gated pause is ACTIONABLE: the result parked the Run on a
       person, which is the definition of handing them the next move.
    4. ``goal_satisfied`` truthy metadata is TERMINAL.
    5. ``requires_actor_action`` truthy metadata is ACTIONABLE.
    6. Everything else is TRANSITIONAL — the conservative default, because a
       result that says nothing still moved state somewhere.
    """
    if not result.success or result.status == "failed":
        return None

    override = (result.metadata or {}).get(RESULT_STATE_METADATA_KEY)
    if override is not None:
        return _result_state_override(override)
    return _result_state_from_metadata(result, dict(result.metadata or {}))


def _result_state_override(override: Any) -> ResultState:
    """The declared result state, refused loudly when it names nothing real."""
    try:
        return ResultState(str(override))
    except ValueError as exc:
        raise ValueError(
            f"node result metadata {RESULT_STATE_METADATA_KEY!r} must be one of "
            f"{[state.value for state in ResultState]}, got {override!r}"
        ) from exc


def _result_state_from_metadata(result: NodeResult, metadata: dict[str, Any]) -> ResultState:
    """The classified state from the result's own signals, in contract order."""
    if (
        result.status == "paused"
        and str(metadata.get("paused_reason") or "") in HUMAN_PAUSE_REASONS
    ):
        return ResultState.ACTIONABLE
    if metadata.get(GOAL_SATISFIED_METADATA_KEY):
        return ResultState.TERMINAL
    if metadata.get(REQUIRES_ACTOR_ACTION_METADATA_KEY):
        return ResultState.ACTIONABLE
    return ResultState.TRANSITIONAL


__all__ = [
    "GOAL_SATISFIED_METADATA_KEY",
    "REQUIRES_ACTOR_ACTION_METADATA_KEY",
    "RESULT_STATE_METADATA_KEY",
    "ResultState",
    "classify_result_state",
]
