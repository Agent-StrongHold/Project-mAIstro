from __future__ import annotations

from datetime import UTC, datetime, timedelta

from maistro.graph import accepted_outcome_id
from maistro.runs import AcceptedNodeOutcome, AttemptResult, AttemptStatus, RunStatus


def _physical() -> AttemptResult:
    return AttemptResult(
        attempt_id="attempt-1",
        node_run_id="node-run-1",
        ordinal=1,
        status=AttemptStatus.COMPLETED,
        result={"value": 7},
        finished_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
    )


def test_default_completed_projection_preserves_identity_across_acceptance_time() -> None:
    physical = _physical()
    first = AcceptedNodeOutcome(
        node_run_id=physical.node_run_id,
        attempt_result=physical,
        logical_status=RunStatus.COMPLETED,
        result=physical.result,
        accepted_at=datetime(2026, 8, 17, 12, 1, tzinfo=UTC),
    )
    later = first.model_copy(update={"accepted_at": first.accepted_at + timedelta(minutes=5)})

    assert accepted_outcome_id(first) == accepted_outcome_id(later)


def test_distinct_logical_dispositions_have_distinct_authoritative_identity() -> None:
    physical = _physical()
    completed = AcceptedNodeOutcome(
        node_run_id=physical.node_run_id,
        attempt_result=physical,
        logical_status=RunStatus.COMPLETED,
        result=physical.result,
    )
    paused = AcceptedNodeOutcome(
        node_run_id=physical.node_run_id,
        attempt_result=physical,
        logical_status=RunStatus.PAUSED,
        result=physical.result,
    )
    failed = AcceptedNodeOutcome(
        node_run_id=physical.node_run_id,
        attempt_result=physical,
        logical_status=RunStatus.FAILED,
        error="domain rejection",
    )

    assert accepted_outcome_id(completed) != accepted_outcome_id(paused)
    assert accepted_outcome_id(paused) != accepted_outcome_id(failed)


def test_transformed_logical_projection_changes_identity() -> None:
    physical = _physical()
    original = AcceptedNodeOutcome(
        node_run_id=physical.node_run_id,
        attempt_result=physical,
        logical_status=RunStatus.COMPLETED,
        result=physical.result,
    )
    transformed = AcceptedNodeOutcome(
        node_run_id=physical.node_run_id,
        attempt_result=physical,
        logical_status=RunStatus.COMPLETED,
        result={"value": 8},
    )

    assert accepted_outcome_id(original) != accepted_outcome_id(transformed)
