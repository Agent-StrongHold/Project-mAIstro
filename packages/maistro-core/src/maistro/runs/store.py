from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from datetime import datetime
from itertools import islice
from typing import Any, Protocol, runtime_checkable

from maistro.graph.definitions import Graph
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.lifecycle import transition_attempt, transition_node_run, transition_run
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
from maistro.runs.sources import ADMISSION_SOURCE, EPHEMERAL_ADMISSION_SOURCES


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
    ) -> Run: ...

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
    ) -> Attempt: ...

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
    ) -> None:
        if prune_target > max_runs:
            raise ValueError("prune_target cannot exceed max_runs")
        self._project_store = project_store
        self._max_runs = max_runs
        self._prune_target = prune_target
        self._runs: OrderedDict[str, Run] = OrderedDict()
        self._node_runs: dict[str, NodeRun] = {}
        self._attempts: dict[str, Attempt] = {}

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
        del self._runs[run_id]
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
    ) -> Run:
        await self._validate_graph_scope(graph)
        if parent_node_run_id is not None and parent_run_id is None:
            raise RunIntegrityError("parent_node_run_id requires parent_run_id")
        if parent_run_id is not None:
            parent = self._require_run(parent_run_id)
            if parent.workspace_id != graph.workspace_id:
                raise RunIntegrityError("child Run cannot cross Workspace boundaries")
            if parent.project_id != graph.project_id and not allow_cross_project:
                raise RunIntegrityError(
                    "child Run cannot implicitly cross Project boundaries; "
                    "caller must authorize and request the destination Project"
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
        )
        self._runs[run.run_id] = run
        self._prune_terminal_runs()
        return run.model_copy(deep=True)

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
        run = self._require_run(run_id)
        updated = transition_run(run, target, at=at, result=result, error=error)
        self._runs[run_id] = updated
        return updated.model_copy(deep=True)

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

    async def create_attempt(
        self,
        node_run_id: str,
        *,
        runtime_id: str = "python",
        executor_id: str = "",
        deadline_at: datetime | None = None,
        resume_checkpoint_id: str | None = None,
        lease_holder: str | None = None,
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
            attempt = Attempt.model_validate(
                {**attempt.model_dump(mode="python"), "execution_lease": lease}
            )
        self._attempts[attempt.attempt_id] = attempt
        return attempt.model_copy(deep=True)

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
]
