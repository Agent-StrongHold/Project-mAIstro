"""The BacklogHistoryEvent contract (#101): kinds, required payloads, immutability."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from maistro.workspaces.backlog_history import (
    DISCOVERED_INITIAL_STATUS,
    BacklogHistoryEvent,
    BacklogHistoryEventKind,
    FieldChange,
    GoalLink,
    ReconciliationReference,
    RunReference,
)


def _event(kind: BacklogHistoryEventKind, **fields: object) -> BacklogHistoryEvent:
    base: dict[str, object] = {
        "workspace_id": "ws-a",
        "project_id": "p-1",
        "item_id": "item-1",
    }
    base.update(fields)
    return BacklogHistoryEvent(kind=kind, **base)  # type: ignore[arg-type]


def test_event_kinds_are_journal_categories_not_work_states() -> None:
    """No kind value is a bare work-state token, so the journal cannot drift
    into a second execution lifecycle (the execution-lifecycles gate reads
    enum vocabularies; these are deliberately not that vocabulary)."""
    work_state_tokens = {
        "created",
        "claimed",
        "blocked",
        "completed",
        "complete",
        "done",
        "failed",
        "running",
        "pending",
        "paused",
        "waiting",
        "active",
    }
    for kind in BacklogHistoryEventKind:
        assert kind.value not in work_state_tokens


def test_timestamps_are_normalised_to_utc() -> None:
    naive = _event(
        BacklogHistoryEventKind.ITEM_RECORDED,
        occurred_at=datetime(2026, 9, 30, 12, 0, 0),
    )
    assert naive.occurred_at.tzinfo is UTC
    offset = _event(
        BacklogHistoryEventKind.ITEM_RECORDED,
        occurred_at=datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC),
    )
    assert offset.occurred_at == naive.occurred_at


def test_blank_scope_ids_are_refused() -> None:
    with pytest.raises(ValidationError):
        _event(BacklogHistoryEventKind.ITEM_RECORDED, item_id="  ")


def test_status_move_needs_two_different_statuses() -> None:
    with pytest.raises(ValidationError, match="from_status and to_status"):
        _event(BacklogHistoryEventKind.STATUS_MOVED)
    with pytest.raises(ValidationError, match="two different statuses"):
        _event(
            BacklogHistoryEventKind.STATUS_MOVED,
            from_status="accepted",
            to_status="accepted",
        )
    moved = _event(
        BacklogHistoryEventKind.STATUS_MOVED,
        from_status="accepted",
        to_status="implemented",
    )
    assert moved.from_status == "accepted"
    assert moved.to_status == "implemented"


def test_closure_without_evidence_is_refused_by_the_model() -> None:
    with pytest.raises(ValidationError, match="evidence_refs"):
        _event(BacklogHistoryEventKind.CLOSURE_RECORDED)


def test_events_are_frozen() -> None:
    event = _event(BacklogHistoryEventKind.ITEM_RECORDED)
    with pytest.raises(ValidationError):
        event.summary = "rewritten"  # type: ignore[misc]


def test_sequence_is_store_assigned() -> None:
    event = _event(BacklogHistoryEventKind.ITEM_RECORDED)
    assert event.sequence is None
    stored = event.model_copy(update={"sequence": 3})
    assert stored.sequence == 3


def test_decomposition_needs_children() -> None:
    with pytest.raises(ValidationError, match="child_item_ids"):
        _event(BacklogHistoryEventKind.DECOMPOSITION_RECORDED)


def test_discovered_work_enters_as_proposed_and_only_proposed() -> None:
    event = _event(
        BacklogHistoryEventKind.DISCOVERED_WORK_RECORDED,
        child_item_ids=("child-1",),
    )
    assert event.child_initial_status is None

    explicit = _event(
        BacklogHistoryEventKind.DISCOVERED_WORK_RECORDED,
        child_item_ids=("child-1",),
        child_initial_status=DISCOVERED_INITIAL_STATUS,
    )
    assert explicit.child_initial_status == "proposed"

    with pytest.raises(ValidationError, match="proposed"):
        _event(
            BacklogHistoryEventKind.DISCOVERED_WORK_RECORDED,
            child_item_ids=("child-1",),
            child_initial_status="accepted",
        )


def test_goal_link_validates_against_the_interop_ontology() -> None:
    link = GoalLink(goal_id="g-1", goal_revision="r4")
    assert link.goal_id == "g-1"
    with pytest.raises(ValidationError):
        GoalLink(goal_id="  ", goal_revision="r4")
    with pytest.raises(ValidationError):
        GoalLink(goal_id="g-1")  # type: ignore[call-arg]


def test_goal_bound_requires_the_link() -> None:
    with pytest.raises(ValidationError, match="goal_link"):
        _event(BacklogHistoryEventKind.GOAL_BOUND)


def test_reconciliation_needs_a_decision_reference() -> None:
    with pytest.raises(ValidationError, match="reconciliation"):
        _event(BacklogHistoryEventKind.RECONCILIATION_RECORDED)


def test_run_evidence_needs_a_reference() -> None:
    with pytest.raises(ValidationError, match="run_refs or evaluation_refs"):
        _event(BacklogHistoryEventKind.RUN_EVIDENCE_RECORDED)


def test_blocker_and_reopen_need_their_reasons() -> None:
    with pytest.raises(ValidationError, match="blocker_reason"):
        _event(BacklogHistoryEventKind.BLOCKER_RECORDED)
    with pytest.raises(ValidationError, match="reason"):
        _event(BacklogHistoryEventKind.REOPENED, reason="  ")


def _registered_validators(model: type) -> set[str]:
    return set(model.__pydantic_decorators__.model_validators)


def test_kind_validators_are_registered_with_pydantic() -> None:
    """The shape checks run because pydantic calls these validators; pinning
    the registered names keeps a rename from silently dropping a check."""
    assert {
        BacklogHistoryEvent._identities.__name__,
        BacklogHistoryEvent._status_shape.__name__,
        BacklogHistoryEvent._recorded_facts.__name__,
        BacklogHistoryEvent._reasoned_facts.__name__,
    } <= _registered_validators(BacklogHistoryEvent)


def test_value_model_validators_are_registered_with_pydantic() -> None:
    assert GoalLink._canonical.__name__ in _registered_validators(GoalLink)
    assert RunReference._non_empty.__name__ in _registered_validators(RunReference)
    assert ReconciliationReference._non_empty.__name__ in _registered_validators(
        ReconciliationReference
    )
    assert FieldChange._non_empty.__name__ in _registered_validators(FieldChange)
