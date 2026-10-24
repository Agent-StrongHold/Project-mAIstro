"""The canonical Goal-context provenance contract (#458, #65).

`maistro.runs.goal_context` is the one spelling of the keys a goal-driven Run
carries and the fail-closed reader every projection must use. The contract:
a Goal context exists only when provenance names BOTH the goal_id and the
exact goal_revision; blank strings are absence; recorded-optional fields are
never defaulted.
"""

from __future__ import annotations

from maistro.runs.goal_context import (
    GOAL_ID_KEY,
    GOAL_REVISION_KEY,
    GoalContext,
    goal_context_of,
)


def test_full_context_round_trips_every_recorded_field() -> None:
    context = goal_context_of(
        {
            GOAL_ID_KEY: "goal-1",
            GOAL_REVISION_KEY: "rev-7",
            "parent_goal_id": "goal-0",
            "accountable_agent_id": "agent-1",
            "desired_state": "shipped",
            "success_condition": "accepted",
            "stop_condition": "withdrawn",
        }
    )
    assert context == GoalContext(
        goal_id="goal-1",
        goal_revision="rev-7",
        parent_goal_id="goal-0",
        accountable_agent_id="agent-1",
        desired_state="shipped",
        success_condition="accepted",
        stop_condition="withdrawn",
    )


def test_minimum_context_is_goal_id_with_exact_revision() -> None:
    assert goal_context_of({GOAL_ID_KEY: "goal-1", GOAL_REVISION_KEY: "rev-1"}) == (
        GoalContext(goal_id="goal-1", goal_revision="rev-1")
    )


def test_a_goal_without_its_revision_is_not_a_goal_context() -> None:
    """Inventing a revision would let a later Goal revision claim evidence
    admitted under an earlier one — the history rewrite `goal_revision`
    exists to prevent."""
    assert goal_context_of({GOAL_ID_KEY: "goal-1"}) is None


def test_blank_identity_is_absence_not_a_context() -> None:
    assert goal_context_of({GOAL_ID_KEY: "  ", GOAL_REVISION_KEY: "rev-1"}) is None
    assert goal_context_of({GOAL_ID_KEY: "goal-1", GOAL_REVISION_KEY: ""}) is None


def test_no_provenance_and_non_string_values_name_no_context() -> None:
    assert goal_context_of(None) is None
    assert goal_context_of({}) is None
    assert goal_context_of({GOAL_ID_KEY: 7, GOAL_REVISION_KEY: "rev-1"}) is None


def test_optional_fields_are_recorded_or_absent_never_defaulted() -> None:
    context = goal_context_of(
        {
            GOAL_ID_KEY: "goal-1",
            GOAL_REVISION_KEY: "rev-1",
            "desired_state": "   ",
            "success_condition": None,
        }
    )
    assert context is not None
    assert context.desired_state is None
    assert context.success_condition is None
    assert context.stop_condition is None
    assert context.parent_goal_id is None
    assert context.accountable_agent_id is None
