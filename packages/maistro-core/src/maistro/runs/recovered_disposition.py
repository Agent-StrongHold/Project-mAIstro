"""Atomic parking disposition for a RECOVERED Attempt (#232 P4a).

After physical reclaim commits ``CANCELLED`` + ``RECOVERED``, logical
NodeRun/Run parking must happen in one store transaction: lock the Run and
every NodeRun (deterministic identity order), read Attempt facts without
Attempt row locks, then apply the reviewed refusal/parking table. Events stay
outside the commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from maistro.runs.lifecycle import latest_node_runs, transition_node_run, transition_run
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    Attempt,
    AttemptStatus,
    CancellationCause,
    NodeRun,
    Run,
    RunStatus,
)

_ACTIVE_NODE = frozenset({RunStatus.CREATED, RunStatus.QUEUED, RunStatus.RUNNING})
_ACTIVE_ATTEMPT = frozenset({AttemptStatus.CREATED, AttemptStatus.RUNNING})
_PARKABLE_NODE = frozenset({RunStatus.RUNNING, RunStatus.WAITING})


class RecoveredDispositionRefused(ValueError):
    """The Attempt is not eligible for recovered logical parking."""


@dataclass(frozen=True)
class RecoveredDispositionPlan:
    """What one atomic recovered disposition write must change.

    ``park_node_run``: transition the Attempt's NodeRun RUNNING→WAITING.
    ``park_run``: transition the parent Run RUNNING→WAITING when nothing else
    is active. Both false means a no-op preserve (already parked / terminal /
    superseded sibling work keeps the parent running).
    """

    park_node_run: bool
    park_run: bool


def is_typed_recovered_attempt(attempt: Attempt) -> bool:
    """Persisted RECOVERED cause — the only rows this disposition may park."""
    return (
        attempt.status is AttemptStatus.CANCELLED
        and attempt.cancellation_cause is CancellationCause.RECOVERED
    )


def _highest_ordinal(attempts: list[Attempt]) -> Attempt | None:
    if not attempts:
        return None
    return max(attempts, key=lambda item: item.ordinal)


def _has_active_physical_work(
    *,
    candidate_node_run_id: str,
    all_node_runs: list[NodeRun],
    attempts_by_node_run: dict[str, list[Attempt]],
    parking_candidate_node: bool,
) -> bool:
    """Any live sibling NodeRun or non-terminal Attempt blocks parent parking."""
    for node_run in all_node_runs:
        if node_run.node_run_id == candidate_node_run_id and parking_candidate_node:
            # Candidate itself is about to leave RUNNING — do not count it.
            pass
        elif node_run.status in _ACTIVE_NODE:
            return True
        for attempt in attempts_by_node_run.get(node_run.node_run_id, ()):
            if attempt.status in _ACTIVE_ATTEMPT:
                return True
    return False


def _assert_recovered_disposition_lineage(*, attempt: Attempt, run: Run, node_run: NodeRun) -> None:
    if not is_typed_recovered_attempt(attempt):
        raise RecoveredDispositionRefused(
            f"Attempt {attempt.attempt_id!r} is not a typed RECOVERED cancellation"
        )
    if attempt.node_run_id != node_run.node_run_id:
        raise RecoveredDispositionRefused("Attempt does not belong to the resolved NodeRun")
    if node_run.run_id != run.run_id:
        raise RecoveredDispositionRefused("NodeRun does not belong to the resolved Run")


def _preserve_recovered_disposition(
    *,
    attempt: Attempt,
    node_run: NodeRun,
    all_node_runs: list[NodeRun],
    attempts_by_node_run: dict[str, list[Attempt]],
) -> RecoveredDispositionPlan | None:
    """Return a no-op plan when parking must be skipped; else ``None`` to continue."""
    latest = latest_node_runs(all_node_runs).get(node_run.node_id)
    if latest is None or latest.node_run_id != node_run.node_run_id:
        return RecoveredDispositionPlan(park_node_run=False, park_run=False)

    peers = attempts_by_node_run.get(node_run.node_run_id, [])
    highest = _highest_ordinal(peers)
    if highest is None or highest.attempt_id != attempt.attempt_id:
        return RecoveredDispositionPlan(park_node_run=False, park_run=False)

    if node_run.status in TERMINAL_RUN_STATUSES or node_run.status is RunStatus.PAUSED:
        return RecoveredDispositionPlan(park_node_run=False, park_run=False)
    return None


def plan_recovered_attempt_disposition(
    *,
    attempt: Attempt,
    run: Run,
    node_run: NodeRun,
    all_node_runs: list[NodeRun],
    attempts_by_node_run: dict[str, list[Attempt]],
) -> RecoveredDispositionPlan:
    """Decide NodeRun/Run parking for one already-persisted RECOVERED Attempt.

    Refusal table (raise, never dispatch):
    - not typed RECOVERED (REQUESTED / unknown / non-CANCELLED)
    - lineage mismatch
    - NodeRun CREATED/QUEUED (prelaunch leaf is out of scope — D.1)

    Preserve table (no-op plan, never dispatch):
    - superseded NodeRun (newer visit for the same ``node_id``)
    - superseded Attempt (higher ordinal on the same NodeRun)
    - NodeRun PAUSED or terminal
    - already WAITING with active siblings (parent stays RUNNING)
    """
    _assert_recovered_disposition_lineage(attempt=attempt, run=run, node_run=node_run)
    preserved = _preserve_recovered_disposition(
        attempt=attempt,
        node_run=node_run,
        all_node_runs=all_node_runs,
        attempts_by_node_run=attempts_by_node_run,
    )
    if preserved is not None:
        return preserved

    park_node = node_run.status is RunStatus.RUNNING
    if node_run.status not in _PARKABLE_NODE:
        raise RecoveredDispositionRefused(
            f"NodeRun {node_run.node_run_id!r} in {node_run.status.value!r} "
            "cannot receive a recovered disposition"
        )

    active = _has_active_physical_work(
        candidate_node_run_id=node_run.node_run_id,
        all_node_runs=all_node_runs,
        attempts_by_node_run=attempts_by_node_run,
        parking_candidate_node=park_node,
    )
    park_run = (not active) and run.status is RunStatus.RUNNING
    return RecoveredDispositionPlan(park_node_run=park_node, park_run=park_run)


def materialize_recovered_disposition_plan(
    plan: RecoveredDispositionPlan,
    *,
    run: Run,
    node_run: NodeRun,
    attempt: Attempt,
    at: datetime | None,
) -> tuple[NodeRun, Run]:
    """Apply a plan with lifecycle transforms; caller persists the results."""
    settled_node = node_run
    settled_run = run
    if plan.park_node_run:
        settled_node = transition_node_run(
            node_run,
            RunStatus.WAITING,
            at=at,
            error=attempt.error,
        )
    if plan.park_run:
        settled_run = transition_run(run, RunStatus.WAITING, at=at)
    return settled_node, settled_run


__all__ = [
    "RecoveredDispositionPlan",
    "RecoveredDispositionRefused",
    "is_typed_recovered_attempt",
    "materialize_recovered_disposition_plan",
    "plan_recovered_attempt_disposition",
]
