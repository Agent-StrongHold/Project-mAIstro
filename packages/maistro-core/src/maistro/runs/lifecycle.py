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


#: What an open NodeRun settles to when its Run terminalizes (ADR-082426-a47f).
#:
#: Not the Run's own terminal status. The node did not succeed, fail or time
#: out — something outside it ended the work, and marking it `failed` under a
#: failed Run would invent a physical outcome it never had and count one failure
#: twice for anyone measuring node failures.
CASCADED_NODE_RUN_STATUS = RunStatus.CANCELLED


def cascaded_node_run_error(run_target: RunStatus) -> str:
    """Why an open NodeRun was settled, naming the Run's own outcome.

    The distinction is the whole value of the field here: without it a cascade
    is indistinguishable from six nodes that were each cancelled individually.
    """
    return f"cancelled because its Run terminalized as {run_target.value}"


def settle_open_node_run(
    node_run: NodeRun,
    run_target: RunStatus,
    *,
    at: datetime | None = None,
) -> NodeRun:
    """Settle one non-terminal NodeRun because its Run is terminalizing.

    Every non-terminal status has an edge to CANCELLED, so this cannot fail on
    a NodeRun the caller has already established is open.

    A paused node's accepted outcome is superseded rather than carried over,
    which `transition_node_run` already does for this target. That is not a
    choice available here: `NodeRun` validates that its status *is* its accepted
    outcome's `logical_status`, because an acceptance states the node's current
    logical disposition rather than recording a past one. A cancelled node whose
    acceptance still read `paused` would be a record claiming both. What the
    paused node was paused for survives where it was written, on the Attempt.
    """
    return transition_node_run(
        node_run,
        CASCADED_NODE_RUN_STATUS,
        at=at,
        error=cascaded_node_run_error(run_target),
    )


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
    "CASCADED_NODE_RUN_STATUS",
    "RUN_TRANSITIONS",
    "InvalidLifecycleTransition",
    "cascaded_node_run_error",
    "settle_open_node_run",
    "transition_attempt",
    "transition_node_run",
    "transition_run",
]
