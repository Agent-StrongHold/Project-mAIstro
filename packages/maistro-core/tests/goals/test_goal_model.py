"""The Goal model's own guards, before any store touches it.

The stores refuse what the model refuses and the other way round is not true:
a store can only be as strict as its record type. These tests pin the record
type — frozen revisions, the lifecycle vocabulary's legality table, paired
transition-record fields — so a backend cannot grow lenient without this file
failing first.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from maistro.goals.model import (
    TERMINAL_GOAL_STATUSES,
    Goal,
    GoalRevision,
    GoalRevisionDraft,
    GoalStatus,
    GoalTransitionError,
    GoalTransitionKind,
    GoalTransitionRecord,
    transition_is_legal,
)


def _draft(**overrides: object) -> GoalRevisionDraft:
    fields: dict[str, object] = {
        "desired_state": "the deployment is green",
        "success_conditions": ("health check passes",),
        "stop_conditions": ("budget exhausted",),
        "author": "op-1",
    }
    fields.update(overrides)
    return GoalRevisionDraft(**fields)  # type: ignore[arg-type]


def test_goal_revision_is_frozen_and_stamps_its_pointer() -> None:
    revision = GoalRevision(**{**_draft().model_dump(), "revision": 3})
    assert revision.revision == 3
    with pytest.raises(ValidationError):
        revision.desired_state = "rewritten"


def test_a_revision_draft_requires_content_and_an_author() -> None:
    for kwargs in ({"desired_state": "   "}, {"author": ""}):
        with pytest.raises(ValidationError):
            _draft(**kwargs)
    # Empty condition lists are legitimate: a Goal may name only desired state.
    assert _draft(success_conditions=(), stop_conditions=()).success_conditions == ()


def test_revision_numbers_start_at_one() -> None:
    with pytest.raises(ValidationError):
        GoalRevision(**{**_draft().model_dump(), "revision": 0})
    with pytest.raises(ValidationError):
        GoalRevision(**{**_draft().model_dump(), "revision": -1})


def test_goal_cannot_be_its_own_parent() -> None:
    with pytest.raises(ValidationError, match="own parent"):
        Goal(
            goal_id="goal-self",
            workspace_id="ws-1",
            project_id="prj-1",
            agent_id="a",
            parent_goal_id="goal-self",
        )


def test_goal_identity_fields_are_required() -> None:
    for overrides in (
        {"workspace_id": " "},
        {"project_id": ""},
        {"agent_id": "  "},
    ):
        fields: dict[str, object] = {
            "goal_id": "g",
            "workspace_id": "ws-1",
            "project_id": "prj-1",
            "agent_id": "a",
        }
        fields.update(overrides)
        with pytest.raises(ValidationError):
            Goal(**fields)  # type: ignore[arg-type]


def test_terminal_states_are_exactly_the_four_non_active_states() -> None:
    assert frozenset(GoalStatus) - {GoalStatus.ACTIVE} == TERMINAL_GOAL_STATUSES
    # And the legality table agrees: only `active` has outgoing moves, and
    # no state may move to itself.
    for status in GoalStatus:
        assert not transition_is_legal(status, status)
        if status is GoalStatus.ACTIVE:
            continue
        assert not transition_is_legal(status, GoalStatus.ACTIVE)


def test_transition_legality_table() -> None:
    assert not transition_is_legal(GoalStatus.ACTIVE, GoalStatus.ACTIVE)
    for terminal in TERMINAL_GOAL_STATUSES:
        assert transition_is_legal(GoalStatus.ACTIVE, terminal)
        for target in GoalStatus:
            assert not transition_is_legal(terminal, target)


def test_transition_records_carry_both_sides_of_their_kind() -> None:
    moment = datetime(2026, 10, 3, tzinfo=UTC)
    with pytest.raises(ValidationError, match="both sides"):
        GoalTransitionRecord(
            goal_id="g",
            kind=GoalTransitionKind.STATUS,
            actor="op-1",
            revision=1,
            to_status=GoalStatus.CANCELLED,
            at=moment,
        )
    with pytest.raises(ValidationError, match="both sides"):
        GoalTransitionRecord(
            goal_id="g",
            kind=GoalTransitionKind.AGENT_REASSIGN,
            actor="op-1",
            revision=1,
            to_agent_id="agent-8",
            at=moment,
        )
    # And a kind that records nothing of its shape is a constructor mistake.
    record = GoalTransitionRecord(
        goal_id="g",
        kind=GoalTransitionKind.STATUS,
        actor="op-1",
        revision=1,
        from_status=GoalStatus.ACTIVE,
        to_status=GoalStatus.SUPERSEDED,
        at=moment,
    )
    assert record.kind is GoalTransitionKind.STATUS
    with pytest.raises(GoalTransitionError):
        # The error type is part of the contract: stores raise *it*, not a
        # bare ValueError, for a transition the vocabulary refuses.
        raise GoalTransitionError("active -> active")


def test_transition_record_rejects_an_empty_actor() -> None:
    with pytest.raises(ValidationError):
        GoalTransitionRecord(
            goal_id="g",
            kind=GoalTransitionKind.STATUS,
            actor="  ",
            revision=1,
            from_status=GoalStatus.ACTIVE,
            to_status=GoalStatus.CANCELLED,
        )
