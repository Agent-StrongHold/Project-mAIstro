from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import islice
from typing import Any, Protocol, runtime_checkable

from maistro.archive.protocols import ArchiveStore
from maistro.graph.definitions import Graph
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.lifecycle import (
    check_completion_is_earned,
    lease_is_expired,
    reclaim_attempt,
    renew_attempt_lease,
    renewed_lease,
    settle_open_node_run,
    transition_attempt,
    transition_node_run,
    transition_run,
)
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    ExecutionLease,
    GraphSnapshot,
    NodeRun,
    Run,
    RunStatus,
    evidence_values_equal,
)
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    EPHEMERAL_ADMISSION_SOURCES,
    occurrence_key,
)

#: How many lapsed Attempts one reclaim sweep settles. Bounded for the same
#: reason the retention sweep is: a recovery pass must not become a long
#: transaction that blocks the workers it is trying to unblock.
DEFAULT_RECLAIM_BATCH = 100


class RunNotFound(KeyError):
    pass


class NodeRunNotFound(KeyError):
    pass


class AttemptNotFound(KeyError):
    pass


class RunIntegrityError(ValueError):
    pass


class ActiveAttemptExists(RunIntegrityError):
    pass


class DuplicateOccurrence(RunIntegrityError):
    """A Run already exists for this `(schedule_id, scheduled_for)` (#220).

    Distinguished from every other integrity failure because the caller's
    correct response is the opposite one: nothing is wrong. Another ticker, or
    this process before a crash, already admitted that firing, and the right
    move is to treat the occurrence as fired and carry on — not to retry it, and
    not to abandon the batch.
    """

    def __init__(self, schedule_id: str, scheduled_for: str) -> None:
        self.schedule_id = schedule_id
        self.scheduled_for = scheduled_for
        super().__init__(
            f"schedule {schedule_id!r} already has a Run for occurrence {scheduled_for!r}"
        )


def validate_accepted_outcome_against_attempt(
    outcome: AcceptedNodeOutcome,
    attempt: Attempt,
) -> None:
    """Require authoritative logical evidence to match one canonical persisted Attempt."""
    expected = AttemptResult.from_attempt(attempt)
    actual = outcome.attempt_result
    if (
        actual.attempt_id != expected.attempt_id
        or actual.node_run_id != expected.node_run_id
        or actual.ordinal != expected.ordinal
        or actual.status is not expected.status
        or actual.finished_at != expected.finished_at
        or actual.error != expected.error
        or not evidence_values_equal(actual.result, expected.result)
    ):
        raise RunIntegrityError("accepted outcome does not match its canonical persisted Attempt")


class StaleExecutionFence(RunIntegrityError):
    pass


def validate_child_scope(
    parent: Run,
    *,
    workspace_id: str,
    project_id: str,
    allow_cross_project: bool = False,
) -> None:
    """Refuse a child Run that escapes its parent's scope.

    Split out of `create_run` so a caller can run the same check *before* it
    causes a side effect it cannot take back. `agent.delegate_remote` is the
    case that made this necessary: it dispatched over HTTP (or queued an
    `A2ATask`) and only then asked for a child Run, so a delegation naming a
    foreign Workspace was refused *after* the remote work had already been
    handed over — the node reported failure while unauthorized work carried on
    somewhere else, and a retry dispatched it again.

    Duplicating the two conditions at the call site would have been the smaller
    diff and the worse one: the guard and its pre-flight would drift, and the
    pre-flight is exactly the copy that must not be weaker.
    """
    if parent.workspace_id != workspace_id:
        raise RunIntegrityError("child Run cannot cross Workspace boundaries")
    if parent.project_id != project_id and not allow_cross_project:
        raise RunIntegrityError(
            "child Run cannot implicitly cross Project boundaries; "
            "caller must authorize and request the destination Project"
        )


#: Most Runs one `purge_expired_runs` call may delete.
#:
#: A bound, not a tuning knob. The first sweep after a long outage would
#: otherwise be an unbounded DELETE holding row locks across the whole spine,
#: which is how a retention sweep becomes a reason to disable the retention
#: sweep. Sweeping is opportunistic (ADR-082326-c126), so a backlog larger than
#: one batch simply drains over the next several sweeps.
DEFAULT_PURGE_BATCH = 500


def is_purgeable(run: Run, cutoff: datetime) -> bool:
    """Whether retention may delete this Run as of ``cutoff`` (ADR-082326-c126).

    Three conditions, and all three are load-bearing:

    - a deadline was set at all — `None` means "retain indefinitely", which is
      the default and therefore every Run recorded before retention existed;
    - the deadline has passed;
    - the Run is terminal. The deadline is a floor, not a ceiling: a Run past
      its deadline that is still running keeps its execution identity, because
      deleting the identity of live work is worse than the storage it reclaims.
    """
    return (
        run.retention_expires_at is not None
        and run.retention_expires_at <= cutoff
        and run.status in TERMINAL_RUN_STATUSES
    )


#: How long a Run must have been terminal before the archive sweep considers it
#: cold. A default, not a policy: ADR-082226-f436 open question 1 declined to
#: freeze a number nobody had data for, and decision 10 leaves the horizon to
#: deployment configuration. Ninety days is long enough that nothing routine is
#: archived and short enough that the tier is exercised.
DEFAULT_ARCHIVE_AFTER = timedelta(days=90)


def is_archivable(run: Run, cutoff: datetime, *, archive_after: timedelta) -> bool:
    """Whether the archive sweep may move this Run's payload (f436 decision 10).

    The mirror of :func:`is_purgeable`, and deliberately its complement on the
    first condition rather than a second date of its own:

    - **`retention_expires_at is None`** — nobody chose a deletion date, so the
      Run is kept indefinitely. A Run *with* a deadline is purge-eligible and is
      never archived; decision 2 is explicit that archiving is not a way to
      avoid deciding deletion. Because the field is either null or not, the two
      populations cannot overlap, which is the property a separate
      `archive_after` column on the Run would have destroyed.
    - **terminal** — same reason as purging. Live work keeps its payload where
      it can be read without a network round trip.
    - **terminal for longer than `archive_after`** — measured from
      `finished_at`, which a terminal Run always has (`_validate_finished_at`).
      A Run that somehow lacks one is not archived rather than being treated as
      infinitely old, because "no timestamp" is not evidence of coldness.
    """
    if run.retention_expires_at is not None:
        return False
    if run.status not in TERMINAL_RUN_STATUSES:
        return False
    if run.finished_at is None:
        return False
    return run.finished_at <= cutoff - archive_after


#: States a Run may be created directly in — the entry states a caller can
#: honestly know at admission. Anything terminal is excluded: work that has not
#: started cannot have ended.
_ADMISSIBLE_INITIAL_STATUSES = frozenset({RunStatus.CREATED, RunStatus.QUEUED})


def admit_in_state(run: Run, initial_status: RunStatus) -> Run:
    """Apply the state a Run is created in, before it is written anywhere.

    A Run whose caller already knows it is queued used to be inserted as
    CREATED and transitioned immediately afterwards — two commits on a durable
    store, with a window where a process death left a CREATED Run whose
    provenance named a receipt that was never queued, and which no recovery
    scan looks for. Deciding the state before the single insert closes it.
    """
    if initial_status is RunStatus.CREATED:
        return run
    if initial_status not in _ADMISSIBLE_INITIAL_STATUSES:
        raise RunIntegrityError(
            f"a Run cannot be created in state {initial_status.value!r}; admissible: "
            f"{', '.join(sorted(item.value for item in _ADMISSIBLE_INITIAL_STATUSES))}"
        )
    return transition_run(run, initial_status)


@runtime_checkable
class RunStore(Protocol):
    async def create_run(
        self,
        graph: Graph,
        *,
        parent_run_id: str | None = None,
        parent_node_run_id: str | None = None,
        allow_cross_project: bool = False,
        persona_id: str | None = None,
        actor_principal_id: str | None = None,
        provenance: dict[str, Any] | None = None,
        retention_expires_at: datetime | None = None,
        initial_status: RunStatus = RunStatus.CREATED,
    ) -> Run: ...

    async def purge_expired_runs(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_PURGE_BATCH,
    ) -> int: ...

    async def has_runs_in_project(self, project_id: str) -> bool: ...

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

    async def create_node_run(self, run_id: str, *, node_id: str) -> NodeRun: ...

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

    async def create_attempt(
        self,
        node_run_id: str,
        *,
        runtime_id: str = "python",
        executor_id: str = "",
        deadline_at: datetime | None = None,
        resume_checkpoint_id: str | None = None,
        lease_holder: str | None = None,
        lease_ttl: timedelta | None = None,
    ) -> Attempt: ...

    async def renew_lease(
        self,
        attempt_id: str,
        *,
        fencing_token: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> Attempt: ...

    async def reclaim_expired_attempts(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_RECLAIM_BATCH,
    ) -> list[Attempt]: ...

    async def get_attempt(self, attempt_id: str) -> Attempt | None: ...

    async def list_attempts(self, node_run_id: str) -> list[Attempt]: ...

    async def transition_attempt(
        self,
        attempt_id: str,
        target: AttemptStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
        metrics: dict[str, object] | None = None,
        fencing_token: str | None = None,
    ) -> Attempt: ...

    async def delete_run(self, run_id: str) -> bool: ...


#: Retention bound for the in-memory store. Not a tuning knob so much as an
#: admission that this store is used by long-lived processes: maistro-server
#: creates one Run per submitted task, and nothing else evicts them. `TaskQueue`
#: met the smaller version of this problem and answered it the same way, with
#: the same two numbers — prune terminal entries down to a target rather than
#: trimming one at a time, so the cost is amortised.
MAX_IN_MEMORY_RUNS = 10_000
RUN_PRUNE_TARGET = 8_000


class InMemoryRunStore:
    """Reference lifecycle store for canonical Run -> NodeRun -> Attempt state.

    Bounded: terminal Runs are evicted oldest-first once the store exceeds
    :data:`MAX_IN_MEMORY_RUNS`. Only terminal ones — evicting a live Run would
    delete the execution identity of work still running, which is worse than the
    memory it reclaims. A store that is entirely live at the limit therefore
    keeps growing, and that is the correct failure: it means the process has ten
    thousand unfinished Runs, which is a different problem and should look like
    one.
    """

    def __init__(
        self,
        *,
        project_store: ProjectScopeStore,
        max_runs: int = MAX_IN_MEMORY_RUNS,
        prune_target: int = RUN_PRUNE_TARGET,
        archive_store: ArchiveStore | None = None,
    ) -> None:
        if prune_target > max_runs:
            raise ValueError("prune_target cannot exceed max_runs")
        self._project_store = project_store
        # None is the default and means the tier is off (f436 decision 9): no
        # archive store configured is today's behaviour unchanged, with no
        # warning, because warning on a deliberate choice is how operators
        # learn to ignore warnings.
        self._archive_store = archive_store
        self._max_runs = max_runs
        self._prune_target = prune_target
        self._runs: OrderedDict[str, Run] = OrderedDict()
        self._node_runs: dict[str, NodeRun] = {}
        self._attempts: dict[str, Attempt] = {}
        # `(schedule_id, scheduled_for)` -> run_id, for the Runs that claim an
        # occurrence (#220). Held beside the Runs rather than derived by
        # scanning them, because the check is on the hot admission path and a
        # scan would be linear in every Run the store holds.
        self._occurrences: dict[tuple[str, str], str] = {}

    def _prune_terminal_runs(self) -> None:
        """Evict the oldest terminal Runs once the store exceeds its bound.

        Ephemeral sources first (:data:`EPHEMERAL_ADMISSION_SOURCES`). Without
        that ordering this bound is source-agnostic, so a burst of chat turns
        evicts the oldest *task* Runs to make room for itself — thousands of
        task receipts left holding a `run_id` that no longer resolves, which is
        the exact cross-eviction the chat retention policy claims to prevent
        (ADR-082326-c126). The admitter's own window cannot prevent it either,
        because this runs inside `create_run`, before any admitter sees the new
        Run.
        """
        if len(self._runs) <= self._max_runs:
            return
        budget = len(self._runs) - self._prune_target
        for run_id in list(islice(self._evictable(ephemeral_only=True), budget)):
            self._forget_run(run_id)
        # Durable-source Runs are touched only if the store is *still* over its
        # hard bound — never merely to reach the softer prune target. Falling
        # through on the target would evict a task Run for every chat turn once
        # the ephemeral supply ran out, which is the same cross-eviction by a
        # slower route.
        if len(self._runs) <= self._max_runs:
            return
        remaining = len(self._runs) - self._prune_target
        for run_id in list(islice(self._evictable(ephemeral_only=False), remaining)):
            self._forget_run(run_id)

    def _evictable(self, *, ephemeral_only: bool) -> Iterator[str]:
        """Terminal Run ids in admission order, oldest first."""
        for run_id, run in self._runs.items():
            if run.status not in TERMINAL_RUN_STATUSES:
                continue
            source = run.provenance.get(ADMISSION_SOURCE)
            if ephemeral_only and source not in EPHEMERAL_ADMISSION_SOURCES:
                continue
            yield run_id

    def _forget_run(self, run_id: str) -> None:
        """Drop a Run and everything hanging off it.

        The NodeRuns and Attempts go with it. Leaving them would keep the larger
        half of the memory while removing the index into it — a leak that is
        also unreachable.
        """
        forgotten = self._runs.pop(run_id)
        # The claim goes with the Run, so a Run this store evicted or a
        # retention sweep deleted stops blocking its occurrence. That is the
        # right coupling: nothing is duplicated by re-admitting a firing whose
        # only record has been deliberately destroyed, and keeping the claim
        # would be an unreachable row asserting something no longer true.
        occurrence = occurrence_key(forgotten.provenance)
        if occurrence is not None and self._occurrences.get(occurrence) == run_id:
            del self._occurrences[occurrence]
        node_run_ids = {
            node_run_id
            for node_run_id, node_run in self._node_runs.items()
            if node_run.run_id == run_id
        }
        for node_run_id in node_run_ids:
            del self._node_runs[node_run_id]
        for attempt_id in [
            attempt_id
            for attempt_id, attempt in self._attempts.items()
            if attempt.node_run_id in node_run_ids
        ]:
            del self._attempts[attempt_id]

    async def create_run(
        self,
        graph: Graph,
        *,
        parent_run_id: str | None = None,
        parent_node_run_id: str | None = None,
        allow_cross_project: bool = False,
        persona_id: str | None = None,
        actor_principal_id: str | None = None,
        provenance: dict[str, Any] | None = None,
        retention_expires_at: datetime | None = None,
        initial_status: RunStatus = RunStatus.CREATED,
    ) -> Run:
        await self._validate_graph_scope(graph)
        if parent_node_run_id is not None and parent_run_id is None:
            raise RunIntegrityError("parent_node_run_id requires parent_run_id")
        if parent_run_id is not None:
            parent = self._require_run(parent_run_id)
            validate_child_scope(
                parent,
                workspace_id=graph.workspace_id,
                project_id=graph.project_id,
                allow_cross_project=allow_cross_project,
            )
            if parent_node_run_id is not None:
                parent_node_run = self._require_node_run(parent_node_run_id)
                if parent_node_run.run_id != parent_run_id:
                    raise RunIntegrityError("parent_node_run_id does not belong to parent_run_id")
        run = Run(
            workspace_id=graph.workspace_id,
            project_id=graph.project_id,
            graph=GraphSnapshot.from_graph(graph.model_copy(deep=True)),
            parent_run_id=parent_run_id,
            parent_node_run_id=parent_node_run_id,
            persona_id=persona_id,
            actor_principal_id=actor_principal_id,
            provenance=dict(provenance or {}),
            retention_expires_at=retention_expires_at,
        )
        run = admit_in_state(run, initial_status)
        occurrence = occurrence_key(run.provenance)
        if occurrence is not None:
            # Checked and claimed with no await between, which is what makes
            # this atomic here: this store runs in one event loop, and the two
            # halves cannot be interleaved by another coroutine. The durable
            # backends get the same guarantee from a unique index instead.
            if occurrence in self._occurrences:
                raise DuplicateOccurrence(*occurrence)
            self._occurrences[occurrence] = run.run_id
        self._runs[run.run_id] = run
        self._prune_terminal_runs()
        return run.model_copy(deep=True)

    def _referenced_by_children(self) -> tuple[set[str], set[str]]:
        """The Run and NodeRun ids some other Run names as its parent."""
        parent_runs = {
            run.parent_run_id for run in self._runs.values() if run.parent_run_id is not None
        }
        parent_node_runs = {
            run.parent_node_run_id
            for run in self._runs.values()
            if run.parent_node_run_id is not None
        }
        return parent_runs, parent_node_runs

    def _has_child(
        self,
        run_id: str,
        parent_runs: set[str],
        parent_node_runs: set[str],
    ) -> bool:
        if run_id in parent_runs:
            return True
        return any(
            node_run.node_run_id in parent_node_runs
            for node_run in self._node_runs.values()
            if node_run.run_id == run_id
        )

    async def purge_expired_runs(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_PURGE_BATCH,
    ) -> int:
        """Delete up to ``limit`` expired terminal Runs. Returns how many went.

        Orphan-safe: a Run some other Run descends from is skipped, however
        expired. The durable backend enforces that with `ON DELETE RESTRICT`
        and this one must agree, or the same retention policy would produce a
        dangling parent pointer here and an integrity error there.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        cutoff = now if now is not None else datetime.now(UTC)
        parent_runs, parent_node_runs = self._referenced_by_children()
        doomed = [
            run_id
            for run_id, run in self._runs.items()
            if is_purgeable(run, cutoff)
            and not self._has_child(run_id, parent_runs, parent_node_runs)
        ]
        for run_id in doomed[:limit]:
            await self.delete_run(run_id, force=True)
        return min(len(doomed), limit)

    async def archive_cold_runs(
        self,
        *,
        now: datetime | None = None,
        archive_after: timedelta = DEFAULT_ARCHIVE_AFTER,
        limit: int = DEFAULT_PURGE_BATCH,
    ) -> int:
        """Archive up to ``limit`` cold Runs. Returns how many went.

        The counterpart of :meth:`purge_expired_runs`, and deliberately not part
        of it: :func:`is_archivable` and :func:`is_purgeable` select disjoint
        populations, because f436 decision 2 refuses to let archiving stand in
        for a deletion decision.

        This store keeps the Run resident after archiving, which is not a
        shortcut. `InMemoryRunStore` is the reference implementation of the
        *protocol*, not a tier that saves bytes — it is already bounded by
        eviction. What it must prove is the contract the durable stores are held
        to: that the payload reaches the archive, and that a read afterwards
        still returns the record rather than an empty result.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        if self._archive_store is None:
            return 0
        cutoff = now if now is not None else datetime.now(UTC)
        cold = [
            run
            for run in self._runs.values()
            if is_archivable(run, cutoff, archive_after=archive_after)
        ]
        for run in cold[:limit]:
            await self._archive_store.put(
                run.model_dump_json().encode("utf-8"), scope=run.project_id
            )
        return min(len(cold), limit)

    async def has_runs_in_project(self, project_id: str) -> bool:
        """Whether any Run is filed in this Project.

        Consulted by `InMemoryProjectScopeStore.delete()` so a Project cannot
        be deleted out from under its Run history. PostgreSQL enforces the same
        rule with a foreign key; this is the reference store's equivalent.
        """
        return any(run.project_id == project_id for run in self._runs.values())

    async def get_run(self, run_id: str) -> Run | None:
        run = self._runs.get(run_id)
        return run.model_copy(deep=True) if run is not None else None

    async def transition_run(
        self,
        run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
    ) -> Run:
        """Advance one Run, settling its open NodeRuns when it terminalizes.

        The cascade is ADR-082426-a47f's: a Run that says the work is over
        while a node under it still says `running` is a record nothing can
        read correctly, and every domain that terminalizes a Run does so from
        its own outcome without knowing what nodes exist.

        Every write lands together. The Run's own transition is validated
        first, so an illegal one settles nothing.
        """
        run = self._require_run(run_id)
        check_completion_is_earned(target, self._node_runs_of(run_id))
        updated = transition_run(run, target, at=at, result=result, error=error)
        settled = (
            [
                settle_open_node_run(node_run, target, at=at)
                for node_run in self._open_node_runs(run_id)
            ]
            if target in TERMINAL_RUN_STATUSES
            else []
        )
        self._runs[run_id] = updated
        for node_run in settled:
            self._node_runs[node_run.node_run_id] = node_run
        return updated.model_copy(deep=True)

    def _node_runs_of(self, run_id: str) -> list[NodeRun]:
        return [nr for nr in self._node_runs.values() if nr.run_id == run_id]

    def _open_node_runs(self, run_id: str) -> list[NodeRun]:
        """Every NodeRun under this Run that has not reached a terminal status.

        Ordered by ordinal so the three backends settle in one order, which is
        what lets a conformance suite compare their results directly.
        """
        return sorted(
            (
                node_run
                for node_run in self._node_runs.values()
                if node_run.run_id == run_id and node_run.status not in TERMINAL_RUN_STATUSES
            ),
            key=lambda node_run: node_run.ordinal,
        )

    async def delete_run(self, run_id: str, *, force: bool = False) -> bool:
        """Forget one terminal Run and everything hanging off it.

        False when the Run does not exist, so a retention sweep that races
        another sweep is a no-op rather than an error. Refuses a non-terminal
        Run: deleting the execution identity of work that is still running
        would leave the work itself running with nothing recording it, which is
        worse than the memory it reclaims. ``force`` is for a caller that has
        already established the Run is abandoned.
        """
        run = self._runs.get(run_id)
        if run is None:
            return False
        if run.status not in TERMINAL_RUN_STATUSES and not force:
            raise RunIntegrityError(
                f"cannot delete Run {run_id!r} in non-terminal status {run.status.value!r}"
            )
        children = [child.run_id for child in self._runs.values() if child.parent_run_id == run_id]
        if children:
            raise RunIntegrityError(
                f"cannot delete Run {run_id!r} while {len(children)} child Run(s) reference it; "
                "delete the descendants first"
            )
        self._forget_run(run_id)
        return True

    async def create_node_run(self, run_id: str, *, node_id: str) -> NodeRun:
        run = self._require_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            raise RunIntegrityError("cannot create NodeRun under a terminal Run")
        graph = run.graph.materialize()
        if not any(node.node_id == node_id for node in graph.nodes):
            raise RunIntegrityError(f"node_id {node_id!r} is not present in the Run Graph snapshot")
        ordinal = 1 + sum(node_run.run_id == run_id for node_run in self._node_runs.values())
        node_run = NodeRun(run_id=run_id, node_id=node_id, ordinal=ordinal)
        self._node_runs[node_run.node_run_id] = node_run
        return node_run.model_copy(deep=True)

    async def get_node_run(self, node_run_id: str) -> NodeRun | None:
        node_run = self._node_runs.get(node_run_id)
        return node_run.model_copy(deep=True) if node_run is not None else None

    async def list_node_runs(self, run_id: str) -> list[NodeRun]:
        self._require_run(run_id)
        node_runs = [
            node_run.model_copy(deep=True)
            for node_run in self._node_runs.values()
            if node_run.run_id == run_id
        ]
        node_runs.sort(key=lambda item: item.ordinal)
        return node_runs

    async def transition_node_run(
        self,
        node_run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
        accepted_outcome: AcceptedNodeOutcome | None = None,
    ) -> NodeRun:
        node_run = self._require_node_run(node_run_id)
        self._refuse_under_terminal_run(node_run)
        if accepted_outcome is not None:
            if accepted_outcome.node_run_id != node_run_id:
                raise RunIntegrityError("accepted outcome belongs to a different NodeRun")
            attempt = self._require_attempt(accepted_outcome.attempt_result.attempt_id)
            validate_accepted_outcome_against_attempt(accepted_outcome, attempt)
        updated = transition_node_run(
            node_run,
            target,
            at=at,
            result=result,
            error=error,
            accepted_outcome=accepted_outcome,
        )
        self._node_runs[node_run_id] = updated
        return updated.model_copy(deep=True)

    def _refuse_under_terminal_run(self, node_run: NodeRun) -> None:
        """Refuse to move a NodeRun whose Run has already finished.

        `create_node_run` has always refused under a terminal Run; without the
        same rule here a reconciliation that lands late rewrites the history of
        a closed Run, and can undo the very cascade that settled it.
        """
        run = self._runs.get(node_run.run_id)
        if run is not None and run.status in TERMINAL_RUN_STATUSES:
            raise RunIntegrityError(
                f"cannot transition NodeRun {node_run.node_run_id!r}: "
                f"Run {run.run_id!r} is terminal ({run.status.value})"
            )

    async def create_attempt(
        self,
        node_run_id: str,
        *,
        runtime_id: str = "python",
        executor_id: str = "",
        deadline_at: datetime | None = None,
        resume_checkpoint_id: str | None = None,
        lease_holder: str | None = None,
        lease_ttl: timedelta | None = None,
    ) -> Attempt:
        node_run = self._require_node_run(node_run_id)
        if node_run.status in TERMINAL_RUN_STATUSES:
            raise RunIntegrityError("cannot create Attempt under a terminal NodeRun")
        existing = [
            attempt for attempt in self._attempts.values() if attempt.node_run_id == node_run_id
        ]
        if any(
            attempt.status in {AttemptStatus.CREATED, AttemptStatus.RUNNING} for attempt in existing
        ):
            raise ActiveAttemptExists(f"NodeRun {node_run_id!r} already has an active Attempt")
        ordinal = max((attempt.ordinal for attempt in existing), default=0) + 1
        attempt = Attempt(
            node_run_id=node_run_id,
            ordinal=ordinal,
            runtime_id=runtime_id,
            executor_id=executor_id,
            deadline_at=deadline_at,
            resume_checkpoint_id=resume_checkpoint_id,
        )
        if lease_holder is not None:
            lease = ExecutionLease(
                node_run_id=node_run_id,
                attempt_id=attempt.attempt_id,
                lease_epoch=ordinal,
                holder=lease_holder,
            )
            if lease_ttl is not None:
                lease = renewed_lease(lease, at=lease.issued_at, ttl=lease_ttl)
            attempt = Attempt.model_validate(
                {**attempt.model_dump(mode="python"), "execution_lease": lease}
            )
        self._attempts[attempt.attempt_id] = attempt
        return attempt.model_copy(deep=True)

    async def renew_lease(
        self,
        attempt_id: str,
        *,
        fencing_token: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> Attempt:
        """Prove the holder is still alive, and push its expiry out by ``ttl``."""
        attempt = self._require_attempt(attempt_id)
        renewed = renew_attempt_lease(attempt, fencing_token=fencing_token, ttl=ttl, at=at)
        self._attempts[attempt_id] = renewed
        return renewed.model_copy(deep=True)

    async def reclaim_expired_attempts(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_RECLAIM_BATCH,
    ) -> list[Attempt]:
        """Terminalize Attempts whose holder stopped renewing. Returns them."""
        moment = now if now is not None else datetime.now(UTC)
        doomed = sorted(
            (a for a in self._attempts.values() if lease_is_expired(a, moment)),
            key=lambda a: (a.execution_lease.expires_at, a.attempt_id),  # type: ignore[union-attr]
        )
        reclaimed: list[Attempt] = []
        for attempt in doomed[:limit]:
            settled = reclaim_attempt(attempt, at=moment)
            self._attempts[attempt.attempt_id] = settled
            reclaimed.append(settled.model_copy(deep=True))
        return reclaimed

    async def get_attempt(self, attempt_id: str) -> Attempt | None:
        attempt = self._attempts.get(attempt_id)
        return attempt.model_copy(deep=True) if attempt is not None else None

    async def list_attempts(self, node_run_id: str) -> list[Attempt]:
        self._require_node_run(node_run_id)
        attempts = [
            attempt.model_copy(deep=True)
            for attempt in self._attempts.values()
            if attempt.node_run_id == node_run_id
        ]
        attempts.sort(key=lambda item: item.ordinal)
        return attempts

    async def transition_attempt(
        self,
        attempt_id: str,
        target: AttemptStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
        metrics: dict[str, object] | None = None,
        fencing_token: str | None = None,
    ) -> Attempt:
        attempt = self._require_attempt(attempt_id)
        self._validate_fence(attempt, fencing_token)
        updated = transition_attempt(
            attempt,
            target,
            at=at,
            result=result,
            error=error,
            metrics=metrics,
        )
        self._attempts[attempt_id] = updated
        return updated.model_copy(deep=True)

    @staticmethod
    def _validate_fence(attempt: Attempt, fencing_token: str | None) -> None:
        lease = attempt.execution_lease
        if lease is not None and fencing_token != lease.fencing_token:
            raise StaleExecutionFence(
                f"Attempt {attempt.attempt_id!r} update rejected by execution fence"
            )

    async def _validate_graph_scope(self, graph: Graph) -> None:
        project = await self._project_store.get(graph.project_id)
        if project is None:
            raise RunIntegrityError(
                f"Graph Project {graph.project_id!r} does not exist in canonical Project scope"
            )
        if project.workspace_id != graph.workspace_id:
            raise RunIntegrityError("Graph Project does not belong to the Graph Workspace")

    def _require_run(self, run_id: str) -> Run:
        run = self._runs.get(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    def _require_node_run(self, node_run_id: str) -> NodeRun:
        node_run = self._node_runs.get(node_run_id)
        if node_run is None:
            raise NodeRunNotFound(node_run_id)
        return node_run

    def _require_attempt(self, attempt_id: str) -> Attempt:
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            raise AttemptNotFound(attempt_id)
        return attempt


__all__ = [
    "ActiveAttemptExists",
    "AttemptNotFound",
    "InMemoryRunStore",
    "NodeRunNotFound",
    "RunIntegrityError",
    "RunNotFound",
    "RunStore",
    "StaleExecutionFence",
    "validate_accepted_outcome_against_attempt",
    "validate_child_scope",
]
