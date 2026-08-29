"""Policy-neutral reconciliation between physical Attempts and logical execution.

The reconciler owns universal lifecycle bookkeeping only. It never decides
whether a failed/timed-out/cancelled Attempt is eligible for retry and it never
decides Graph traversal completion. Physical completion is first captured as
immutable AttemptResult evidence; only an explicit AcceptedNodeOutcome makes
a projected result authoritative for the logical NodeRun.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from maistro.runs.aggregation import derive_run_terminal_status, terminal_run_payload
from maistro.runs.lifecycle import InvalidLifecycleTransition, latest_node_runs
from maistro.runs.model import (
    PAUSE_AWAITS_HUMAN,
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    CancellationCause,
    NodeRun,
    Run,
    RunStatus,
    evidence_values_equal,
)
from maistro.runs.recovery_events import RecoveryEventSink, recovery_event
from maistro.runs.store import RunIntegrityError


def _awaits_human(attempt: Attempt) -> bool:
    """Whether a yielded Attempt recorded that it waits on a person."""
    result = attempt.result
    return isinstance(result, dict) and bool(result.get(PAUSE_AWAITS_HUMAN))


class SupersededAttempt(RunIntegrityError):
    """A worker tried to commit an outcome for an Attempt that is no longer current.

    The fence on `transition_attempt` stops a stale worker writing to the
    *physical* record. Nothing stopped it writing the *logical* one: matching
    evidence for a superseded Attempt is exactly what a stale worker holds, so
    "does this evidence match the persisted Attempt" was a check it always
    passed (#238).
    """

    def __init__(self, attempt_id: str, current_attempt_id: str) -> None:
        self.attempt_id = attempt_id
        self.current_attempt_id = current_attempt_id
        super().__init__(
            f"Attempt {attempt_id!r} is superseded by {current_attempt_id!r}; "
            "a stale worker cannot commit into a newer Attempt"
        )


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

    async def list_attempts(self, node_run_id: str) -> list[Attempt]: ...


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


def _graph_has_cycle(run: Run) -> bool:
    """Whether generic reconciliation lacks enough frontier truth to settle this Graph."""
    graph = run.graph.materialize()
    indegree = {node.node_id: 0 for node in graph.nodes}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in indegree}
    for edge in graph.edges:
        outgoing[edge.from_node].append(edge.to_node)
        indegree[edge.to_node] += 1
    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        node_id = ready.pop()
        visited += 1
        for successor in outgoing[node_id]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
    return visited != len(indegree)


class AttemptLifecycleReconciler:
    """Keep Run/NodeRun activity consistent with canonical physical Attempts."""

    def __init__(
        self,
        store: AttemptLifecycleStore,
        *,
        events: RecoveryEventSink | None = None,
        source: str = "maistro.runs.reconciliation",
    ) -> None:
        self._store = store
        self._events = events
        self._source = source

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
                    # Acceptance and parent settlement are separate durable writes.
                    # A crash between them must be repairable by replaying the
                    # already-persisted Attempt rather than stranding the Run.
                    await self._settle_run_if_fully_observed(node_run.run_id)
                    return node_run
                raise RunIntegrityError("NodeRun already accepted a different AttemptResult")
            outcome = AcceptedNodeOutcome(
                node_run_id=node_run.node_run_id,
                attempt_result=physical,
                logical_status=RunStatus.COMPLETED,
                result=physical.result,
            )
            settled = await self._accept_node_outcome(node_run, outcome)
            await self._settle_run_if_fully_observed(settled.run_id)
            await self._announce(persisted, settled, cancellation)
            return settled

        if (
            attempt.status is AttemptStatus.CANCELLED
            and cancellation is CancellationCause.REQUESTED
        ):
            terminal = await self._cancel_node_run(node_run, attempt)
            await self._announce(persisted, terminal, cancellation)
            return terminal

        if attempt.status is AttemptStatus.YIELDED:
            # A pause, not a failure. The disposition is read off the persisted
            # Attempt rather than passed in, so a process that restarts and
            # reconciles this already-durable row lands on the same answer as
            # the one that wrote it.
            paused = await self._pause_node_run(node_run, persisted)
            await self._park_run_if_inactive(paused.run_id)
            await self._announce(persisted, paused, cancellation)
            return paused

        parked = await self._park_node_run(node_run, attempt)
        await self._park_run_if_inactive(parked.run_id)
        await self._announce(persisted, parked, cancellation)
        return parked

    async def _announce(
        self,
        attempt: Attempt,
        node_run: NodeRun,
        cancellation: CancellationCause,
    ) -> None:
        """Put the applied disposition on the canonical Event stream (#462).

        After the write, not before: an event for a disposition that then
        failed to persist would be worse than no event, because the one thing
        a reader wants from it is that it describes what actually happened.

        A caller with no sink reconciles exactly as it did. An unobservable
        recovery is a real gap -- it is why this exists -- but a recovery that
        refused to run because nothing was listening would be a worse one.
        """
        if self._events is None:
            return
        await self._events.emit(
            recovery_event(
                attempt=attempt,
                node_run=node_run,
                cancellation=cancellation,
                source=self._source,
            )
        )

    async def accept_outcome(self, outcome: AcceptedNodeOutcome) -> NodeRun:
        """Persist an explicit domain interpretation of completed physical evidence.

        Refuses a superseded Attempt (#238). The evidence check below asks
        whether this outcome matches what was persisted, which a stale worker
        passes trivially — it is holding a real result from a real Attempt that
        has since been replaced. Whether that Attempt is still *the* Attempt is
        a different question, and it is the one the fence answers one table
        over.
        """
        node_run = await self._require_node_run(outcome.node_run_id)
        persisted = await self._store.get_attempt(outcome.attempt_result.attempt_id)
        if persisted is None:
            raise RunIntegrityError("accepted outcome references an Attempt that is not persisted")
        physical = AttemptResult.from_attempt(persisted)
        if physical != outcome.attempt_result:
            raise RunIntegrityError("accepted outcome differs from persisted Attempt evidence")
        await self._require_current_attempt(outcome.node_run_id, persisted.attempt_id)
        settled = await self._accept_node_outcome(node_run, outcome)
        await self._settle_run_if_fully_observed(settled.run_id)
        return settled

    async def _settle_run_if_fully_observed(self, run_id: str) -> Run:
        """Conservative automatic derivation for direct/fully-materialized work.

        Without graph traversal state, an absent NodeRun may mean an unselected branch
        or work not created yet. Automatic settlement therefore requires every Graph
        node to have been observed and the topology to be acyclic. A cycle can revisit
        an already-observed node, so only a traversal substrate with persisted frontier
        truth may settle it. Such substrates consume the shared aggregation fold once
        their frontier is actually empty.
        """
        run = await self._require_run(run_id)
        if _graph_has_cycle(run):
            return run
        return await self._settle_run_from_node_runs(
            run_id,
            work_owed=False,
            require_all_graph_nodes=True,
        )

    async def _settle_run_from_node_runs(
        self,
        run_id: str,
        *,
        work_owed: bool,
        require_all_graph_nodes: bool,
    ) -> Run:
        run = await self._require_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES or run.status is not RunStatus.RUNNING:
            return run
        node_runs = await self._store.list_node_runs(run_id)
        if require_all_graph_nodes:
            required = {node.node_id for node in run.graph.materialize().nodes}
            observed = set(latest_node_runs(node_runs))
            if not required.issubset(observed):
                return run
        target = derive_run_terminal_status(node_runs, work_owed=work_owed)
        if target is None:
            return run
        result, error = terminal_run_payload(node_runs, target)
        try:
            return await self._store.transition_run(
                run_id,
                target,
                result=result,
                error=error,
            )
        except InvalidLifecycleTransition:
            # Two final NodeRuns can reconcile together. Both may derive the same
            # answer from a complete frontier; the loser observes the winner rather
            # than turning a deterministic race into a failure.
            current = await self._require_run(run_id)
            if current.status in TERMINAL_RUN_STATUSES:
                return current
            raise

    async def _require_current_attempt(self, node_run_id: str, attempt_id: str) -> None:
        """Refuse a commit from any Attempt but the newest under this NodeRun.

        Newest by ordinal rather than by list position: `create_attempt`
        allocates ordinals under a row lock, so the highest one is the Attempt
        that most recently claimed the NodeRun, whatever order a store returns
        rows in.
        """
        attempts = await self._store.list_attempts(node_run_id)
        if not attempts:  # pragma: no cover - the caller already loaded one
            return
        current = max(attempts, key=lambda attempt: attempt.ordinal)
        if current.attempt_id != attempt_id:
            raise SupersededAttempt(attempt_id, current.attempt_id)

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

    async def _pause_node_run(self, node_run: NodeRun, attempt: Attempt) -> NodeRun:
        """Park a yielded NodeRun as PAUSED when a human is what it waits for.

        WAITING and PAUSED are both parked, and the difference is who is
        expected to act: WAITING means a retry decision is owed by the system,
        PAUSED that a person is. Collapsing the two would make a prompt nobody
        can see indistinguishable from a provider being down -- the same
        reading #230 removed one level up for cancellation.
        """
        if node_run.status in TERMINAL_RUN_STATUSES or node_run.status in {
            RunStatus.WAITING,
            RunStatus.PAUSED,
        }:
            return node_run
        if node_run.status is not RunStatus.RUNNING:
            raise RunIntegrityError("terminal Attempt requires a running logical NodeRun")
        target = RunStatus.PAUSED if _awaits_human(attempt) else RunStatus.WAITING
        return await self._store.transition_node_run(node_run.node_run_id, target)

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


__all__ = [
    "AttemptLifecycleReconciler",
    "AttemptLifecycleStore",
    "CancellationCause",
    "SupersededAttempt",
]
