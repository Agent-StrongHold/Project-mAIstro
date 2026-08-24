"""Policy-neutral reconciliation between physical Attempts and logical execution.

The reconciler owns universal lifecycle bookkeeping only. It never decides
whether a failed/timed-out/cancelled Attempt is eligible for retry and it never
decides Graph traversal completion. Physical completion is first captured as
immutable AttemptResult evidence; only an explicit AcceptedNodeOutcome makes
a projected result authoritative for the logical NodeRun.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    NodeRun,
    Run,
    RunStatus,
    evidence_values_equal,
)
from maistro.runs.store import RunIntegrityError


class CancellationCause(Enum):
    """Why an Attempt is cancelled — the one thing its status cannot say (#230).

    `AttemptStatus.CANCELLED` carries two meanings that need opposite logical
    projections, and no amount of reading the persisted Attempt tells them
    apart:

    ``REQUESTED``
        Someone asked this work to stop. The retry decision has been made and
        it was *don't*, so the NodeRun is terminal.

    ``RECOVERED``
        A process died mid-Attempt and the physical record is being closed out
        so a *fresh* Attempt can run — `_reconcile_orphaned_attempts`'s case.
        The node is still owed, so it parks exactly as a failure does.

    Two members, deliberately not three: this says why a cancellation happened,
    not what state anything is in, and it must not become a second lifecycle
    (`scripts/check-execution-lifecycles.py`).
    """

    REQUESTED = "requested"
    RECOVERED = "recovered"


@runtime_checkable
class AttemptLifecycleStore(Protocol):
    """Minimal persisted lifecycle contract required around physical Attempts."""

    async def get_run(self, run_id: str) -> Run | None: ...

    async def transition_run(
        self,
        run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
    ) -> Run: ...

    async def get_node_run(self, node_run_id: str) -> NodeRun | None: ...

    async def list_node_runs(self, run_id: str) -> list[NodeRun]: ...

    async def transition_node_run(
        self,
        node_run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
        accepted_outcome: AcceptedNodeOutcome | None = None,
    ) -> NodeRun: ...

    async def get_attempt(self, attempt_id: str) -> Attempt | None: ...


def _same_accepted_projection(
    left: AcceptedNodeOutcome,
    right: AcceptedNodeOutcome,
) -> bool:
    """Compare accepted logical facts while ignoring acceptance wall-clock time."""
    return (
        left.node_run_id == right.node_run_id
        and left.attempt_result == right.attempt_result
        and left.logical_status is right.logical_status
        and evidence_values_equal(left.result, right.result)
        and left.error == right.error
    )


class AttemptLifecycleReconciler:
    """Keep Run/NodeRun activity consistent with canonical physical Attempts."""

    def __init__(self, store: AttemptLifecycleStore) -> None:
        self._store = store

    async def prepare_execution(self, node_run_id: str) -> NodeRun:
        """Put the containing Run and NodeRun in ``running`` before a physical try."""
        node_run = await self._require_node_run(node_run_id)
        run = await self._require_run(node_run.run_id)
        await self._ensure_run_running(run)
        return await self._ensure_node_run_running(node_run)

    async def reconcile(
        self,
        attempt: Attempt,
        *,
        cancellation: CancellationCause = CancellationCause.RECOVERED,
    ) -> NodeRun:
        """Reconcile one already-persisted terminal Attempt into logical activity.

        ``cancellation`` is read only for a CANCELLED Attempt, and says which of
        its two meanings this one is. It defaults to ``RECOVERED`` — the parking
        behaviour every caller had before #230 — because the two mistakes are
        not symmetric: defaulting to parked leaves a less informative record,
        while defaulting to terminal would make crash recovery destroy the work
        it exists to resume.
        """
        if attempt.status not in TERMINAL_ATTEMPT_STATUSES:
            raise RunIntegrityError("cannot reconcile a non-terminal Attempt")

        persisted = await self._store.get_attempt(attempt.attempt_id)
        if persisted is None:
            raise RunIntegrityError("cannot reconcile an Attempt that is not persisted")
        if persisted.status is not attempt.status:
            raise RunIntegrityError("Attempt reconciliation status differs from persisted state")

        node_run = await self._require_node_run(attempt.node_run_id)
        if attempt.status is AttemptStatus.COMPLETED:
            physical = AttemptResult.from_attempt(persisted)
            accepted = node_run.accepted_outcome
            if accepted is not None:
                if accepted.attempt_result == physical:
                    return node_run
                raise RunIntegrityError("NodeRun already accepted a different AttemptResult")
            outcome = AcceptedNodeOutcome(
                node_run_id=node_run.node_run_id,
                attempt_result=physical,
                logical_status=RunStatus.COMPLETED,
                result=physical.result,
            )
            return await self._accept_node_outcome(node_run, outcome)

        if (
            attempt.status is AttemptStatus.CANCELLED
            and cancellation is CancellationCause.REQUESTED
        ):
            return await self._cancel_node_run(node_run, attempt)

        parked = await self._park_node_run(node_run, attempt)
        await self._park_run_if_inactive(parked.run_id)
        return parked

    async def accept_outcome(self, outcome: AcceptedNodeOutcome) -> NodeRun:
        """Persist an explicit domain interpretation of completed physical evidence."""
        node_run = await self._require_node_run(outcome.node_run_id)
        persisted = await self._store.get_attempt(outcome.attempt_result.attempt_id)
        if persisted is None:
            raise RunIntegrityError("accepted outcome references an Attempt that is not persisted")
        physical = AttemptResult.from_attempt(persisted)
        if physical != outcome.attempt_result:
            raise RunIntegrityError("accepted outcome differs from persisted Attempt evidence")
        return await self._accept_node_outcome(node_run, outcome)

    async def _ensure_run_running(self, run: Run) -> Run:
        if run.status in TERMINAL_RUN_STATUSES:
            raise RunIntegrityError("cannot execute Attempt under a terminal Run")
        if run.status is RunStatus.RUNNING:
            return run
        if run.status in {RunStatus.CREATED, RunStatus.PAUSED}:
            run = await self._store.transition_run(run.run_id, RunStatus.QUEUED)
        if run.status in {RunStatus.QUEUED, RunStatus.WAITING}:
            return await self._store.transition_run(run.run_id, RunStatus.RUNNING)
        raise RunIntegrityError(
            f"Run {run.run_id!r} cannot enter running from {run.status.value!r}"
        )

    async def _ensure_node_run_running(self, node_run: NodeRun) -> NodeRun:
        if node_run.status in TERMINAL_RUN_STATUSES:
            raise RunIntegrityError("cannot execute Attempt under a terminal NodeRun")
        if node_run.status is RunStatus.RUNNING:
            return node_run
        if node_run.status in {RunStatus.CREATED, RunStatus.PAUSED}:
            node_run = await self._store.transition_node_run(
                node_run.node_run_id,
                RunStatus.QUEUED,
            )
        if node_run.status in {RunStatus.QUEUED, RunStatus.WAITING}:
            return await self._store.transition_node_run(
                node_run.node_run_id,
                RunStatus.RUNNING,
            )
        raise RunIntegrityError(
            f"NodeRun {node_run.node_run_id!r} cannot enter running from {node_run.status.value!r}"
        )

    async def _accept_node_outcome(
        self,
        node_run: NodeRun,
        outcome: AcceptedNodeOutcome,
    ) -> NodeRun:
        accepted = node_run.accepted_outcome
        if accepted is not None:
            if _same_accepted_projection(accepted, outcome):
                return node_run
            raise RunIntegrityError("NodeRun already has a different accepted outcome")
        if node_run.status is RunStatus.COMPLETED:
            return await self._store.transition_node_run(
                node_run.node_run_id,
                RunStatus.COMPLETED,
                result=node_run.result,
                error=node_run.error,
                accepted_outcome=outcome,
            )
        if node_run.status is not RunStatus.RUNNING:
            raise RunIntegrityError("completed Attempt requires a running logical NodeRun")
        return await self._store.transition_node_run(
            node_run.node_run_id,
            outcome.logical_status,
            result=outcome.result,
            error=outcome.error,
            accepted_outcome=outcome,
        )

    async def _park_node_run(self, node_run: NodeRun, attempt: Attempt) -> NodeRun:
        if node_run.status in TERMINAL_RUN_STATUSES or node_run.status in {
            RunStatus.WAITING,
            RunStatus.PAUSED,
        }:
            return node_run
        if node_run.status is not RunStatus.RUNNING:
            raise RunIntegrityError("terminal Attempt requires a running logical NodeRun")
        return await self._store.transition_node_run(
            node_run.node_run_id,
            RunStatus.WAITING,
            error=attempt.error,
        )

    async def _cancel_node_run(self, node_run: NodeRun, attempt: Attempt) -> NodeRun:
        """Terminalize a NodeRun whose Attempt was cancelled on request (#230).

        Parked would be the wrong record: WAITING means "awaiting a retry
        decision", and here that decision has been made. Left parked, a
        cancelled turn is indistinguishable on any dashboard from a provider
        being down — which is the reading terminalization exists to prevent.
        """
        if node_run.status in TERMINAL_RUN_STATUSES:
            return node_run
        cancelled = await self._store.transition_node_run(
            node_run.node_run_id,
            RunStatus.CANCELLED,
            error=attempt.error,
        )
        await self._cancel_run_if_inactive(cancelled.run_id)
        return cancelled

    async def _cancel_run_if_inactive(self, run_id: str) -> Run:
        """Carry a requested cancellation up to the Run, if nothing else is live.

        The same shape as `_park_run_if_inactive` and the same reason it is
        conditional: a sibling node still running means the Run is still
        running, and one cancelled branch does not decide for the others.

        CANCELLED rather than WAITING, because a Run parked awaiting a decision
        that has already been taken is the defect #226 removed one level up.
        The durable Graph executor reached the same answer independently in
        `_persist_cancelled_run`.
        """
        run = await self._require_run(run_id)
        if run.status is not RunStatus.RUNNING:
            return run
        if await self._has_active_node_run(run_id):
            return run
        return await self._store.transition_run(run_id, RunStatus.CANCELLED)

    async def _has_active_node_run(self, run_id: str) -> bool:
        node_runs = await self._store.list_node_runs(run_id)
        return any(
            node_run.status in {RunStatus.CREATED, RunStatus.QUEUED, RunStatus.RUNNING}
            for node_run in node_runs
        )

    async def _park_run_if_inactive(self, run_id: str) -> Run:
        run = await self._require_run(run_id)
        if run.status is not RunStatus.RUNNING:
            return run
        if await self._has_active_node_run(run_id):
            return run
        return await self._store.transition_run(run_id, RunStatus.WAITING)

    async def _require_run(self, run_id: str) -> Run:
        run = await self._store.get_run(run_id)
        if run is None:
            raise RunIntegrityError(f"Run {run_id!r} does not exist")
        return run

    async def _require_node_run(self, node_run_id: str) -> NodeRun:
        node_run = await self._store.get_node_run(node_run_id)
        if node_run is None:
            raise RunIntegrityError(f"NodeRun {node_run_id!r} does not exist")
        return node_run


__all__ = ["AttemptLifecycleReconciler", "AttemptLifecycleStore", "CancellationCause"]
