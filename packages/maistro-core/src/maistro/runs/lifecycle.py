from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    Attempt,
    AttemptStatus,
    NodeRun,
    Run,
    RunStatus,
    evidence_values_equal,
)

RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.TIMED_OUT}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING,
            RunStatus.PAUSED,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }
    ),
    RunStatus.WAITING: frozenset(
        {
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            RunStatus.PAUSED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }
    ),
    RunStatus.PAUSED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED, RunStatus.TIMED_OUT}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
    RunStatus.TIMED_OUT: frozenset(),
}

ATTEMPT_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.CREATED: frozenset({AttemptStatus.RUNNING, AttemptStatus.CANCELLED}),
    AttemptStatus.RUNNING: frozenset(
        {
            AttemptStatus.COMPLETED,
            AttemptStatus.FAILED,
            AttemptStatus.CANCELLED,
            AttemptStatus.TIMED_OUT,
            AttemptStatus.YIELDED,
        }
    ),
    AttemptStatus.COMPLETED: frozenset(),
    AttemptStatus.FAILED: frozenset(),
    AttemptStatus.CANCELLED: frozenset(),
    AttemptStatus.TIMED_OUT: frozenset(),
    AttemptStatus.YIELDED: frozenset(),
}

_ACCEPTANCE_SUPERSEDING_TRANSITIONS = frozenset(
    {
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }
)


class InvalidLifecycleTransition(ValueError):
    pass


def _now(value: datetime | None) -> datetime:
    return value if value is not None else datetime.now(UTC)


def _validate_run_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in RUN_TRANSITIONS[current]:
        raise InvalidLifecycleTransition(f"illegal transition: {current.value} -> {target.value}")


def _logical_values(
    record: Run | NodeRun,
    target: RunStatus,
    *,
    at: datetime | None,
    result: object | None,
    error: str | None,
) -> dict[str, Any]:
    _validate_run_transition(record.status, target)
    timestamp = _now(at)
    values = record.model_dump(mode="python")
    values["status"] = target
    values["updated_at"] = timestamp
    values["result"] = result
    values["error"] = error
    if target is RunStatus.RUNNING and record.started_at is None:
        values["started_at"] = timestamp
    if target in TERMINAL_RUN_STATUSES:
        values["finished_at"] = timestamp
    return values


def transition_run(
    run: Run,
    target: RunStatus,
    *,
    at: datetime | None = None,
    result: object | None = None,
    error: str | None = None,
) -> Run:
    return Run.model_validate(_logical_values(run, target, at=at, result=result, error=error))


def _migrate_legacy_completed_node_run(
    node_run: NodeRun,
    target: RunStatus,
    accepted_outcome: AcceptedNodeOutcome | None,
) -> NodeRun | None:
    """Install matching accepted evidence on a legacy completed NodeRun."""
    if node_run.status is not RunStatus.COMPLETED or target is not RunStatus.COMPLETED:
        return None
    if node_run.accepted_outcome is not None or accepted_outcome is None:
        raise InvalidLifecycleTransition("illegal transition: completed -> completed")
    if accepted_outcome.logical_status is not RunStatus.COMPLETED:
        raise InvalidLifecycleTransition(
            "legacy completed NodeRun requires a completed accepted outcome"
        )
    if not evidence_values_equal(node_run.result, accepted_outcome.result):
        raise InvalidLifecycleTransition("legacy completed NodeRun result differs from outcome")
    if node_run.error != accepted_outcome.error:
        raise InvalidLifecycleTransition("legacy completed NodeRun error differs from outcome")
    values = node_run.model_dump(mode="python")
    values["accepted_outcome"] = accepted_outcome
    return NodeRun.model_validate(values)


def transition_node_run(
    node_run: NodeRun,
    target: RunStatus,
    *,
    at: datetime | None = None,
    result: object | None = None,
    error: str | None = None,
    accepted_outcome: AcceptedNodeOutcome | None = None,
) -> NodeRun:
    # Compatibility migration for rows completed before AcceptedNodeOutcome
    # existed. This is not a lifecycle transition: it only installs matching
    # authoritative evidence onto an already-terminal logical record while
    # preserving its original lifecycle timestamps.
    migrated = _migrate_legacy_completed_node_run(node_run, target, accepted_outcome)
    if migrated is not None:
        return migrated

    values = _logical_values(node_run, target, at=at, result=result, error=error)
    if (
        node_run.accepted_outcome is not None
        and node_run.status in {RunStatus.WAITING, RunStatus.PAUSED}
        and target in _ACCEPTANCE_SUPERSEDING_TRANSITIONS
    ):
        values["accepted_outcome"] = None
    if accepted_outcome is not None:
        values["accepted_outcome"] = accepted_outcome
    return NodeRun.model_validate(values)


def transition_attempt(
    attempt: Attempt,
    target: AttemptStatus,
    *,
    at: datetime | None = None,
    result: object | None = None,
    error: str | None = None,
    metrics: dict[str, object] | None = None,
) -> Attempt:
    if target not in ATTEMPT_TRANSITIONS[attempt.status]:
        raise InvalidLifecycleTransition(
            f"illegal transition: {attempt.status.value} -> {target.value}"
        )

    timestamp = _now(at)
    values = attempt.model_dump(mode="python")
    values["status"] = target
    values["result"] = result
    values["error"] = error
    if metrics is not None:
        values["metrics"] = metrics
    if target is AttemptStatus.RUNNING and attempt.started_at is None:
        values["started_at"] = timestamp
    if target in TERMINAL_ATTEMPT_STATUSES:
        values["finished_at"] = timestamp
    return Attempt.model_validate(values)


__all__ = [
    "ATTEMPT_TRANSITIONS",
    "RUN_TRANSITIONS",
    "InvalidLifecycleTransition",
    "transition_attempt",
    "transition_node_run",
    "transition_run",
]
