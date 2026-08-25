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


class UnearnedRunCompletion(InvalidLifecycleTransition):
    """A Run claimed COMPLETED while the spine recorded otherwise (#241)."""

    def __init__(self, node_id: str, node_run_id: str, status: RunStatus) -> None:
        self.node_id = node_id
        self.node_run_id = node_run_id
        self.status = status
        super().__init__(
            f"Run cannot complete: its latest NodeRun for node {node_id!r} "
            f"({node_run_id}) is {status.value!r}, not completed"
        )


def latest_node_runs(node_runs: list[NodeRun]) -> dict[str, NodeRun]:
    """The newest NodeRun for each node_id, by ordinal.

    A node can hold more than one NodeRun. A *retry* is a new Attempt under the
    same NodeRun, but a re-execution — a cycle, a resumed frontier — calls
    `execute_node` again and gets a new NodeRun with a higher ordinal for the
    same node. So a node that failed and then succeeded has two, and only the
    newest states its outcome.

    Folding every NodeRun instead would make "this node failed once, long ago"
    permanently fatal to its Run, which would break every retry-after-failure
    path in the repository. This is the same rule the fence needs one level
    down (ADR-082426-e3ff): the newest record for an identity is the one that
    counts.
    """
    newest: dict[str, NodeRun] = {}
    for node_run in node_runs:
        current = newest.get(node_run.node_id)
        if current is None or node_run.ordinal > current.ordinal:
            newest[node_run.node_id] = node_run
    return newest


def check_completion_is_earned(target: RunStatus, node_runs: list[NodeRun]) -> None:
    """Refuse a COMPLETED Run that contradicts a NodeRun's recorded outcome.

    Two deliberate narrowings, and both are the decision rather than an
    oversight.

    **Only COMPLETED is checked.** The rule is asymmetric because success is
    the only claim that has to be earned. A Run may terminalize as FAILED,
    CANCELLED or TIMED_OUT over nodes that each completed: those outcomes come
    from outside any node — a caller cancelled the work (#230/#233), a deadline
    expired, the fold between nodes raised — and refusing them would leave a
    domain unable to report what actually happened.

    **Only *terminal* NodeRuns are consulted.** A latest NodeRun that is still
    open is ADR-082426-a47f's case, not this one: that ADR decided such a node
    is cascaded to CANCELLED by the very transition being validated here, and
    it decided it for a reason this ADR does not reopen — a graph may abandon a
    node whose result it no longer needs, and a first-wins race is a real
    pattern rather than a bug. So the residual stands and is stated plainly: a
    Run can still complete over a node it cancelled in the same breath.

    What is refused is the contradiction: a Run reporting success while the
    spine holds a *finished* node that failed, was cancelled, or timed out.
    That is the combination #43's fourth criterion calls impossible, and it
    needs no race to produce — the ordinary path produces it.

    A node with no NodeRun at all is not consulted: a Graph node that never ran
    is the ordinary outcome of a conditional branch, not a missing result.
    """
    if target is not RunStatus.COMPLETED:
        return
    for node_id, node_run in sorted(latest_node_runs(node_runs).items()):
        if node_run.status is RunStatus.COMPLETED:
            continue
        if node_run.status in TERMINAL_RUN_STATUSES:
            raise UnearnedRunCompletion(node_id, node_run.node_run_id, node_run.status)


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
    "UnearnedRunCompletion",
    "cascaded_node_run_error",
    "check_completion_is_earned",
    "latest_node_runs",
    "settle_open_node_run",
    "transition_attempt",
    "transition_node_run",
    "transition_run",
]
