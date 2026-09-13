"""Bounded production recovery for persisted canonical Graph work (#837).

This module does not own a queue, timer, Run lifecycle, or execution policy. It
provides recovery ticks over the canonical Run spine and durable Graph
continuations. Physical work still crosses the canonical Attempt/lease/fence
boundary in :mod:`attempt_executor`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes.base import PAUSE_RESUME_CONDITIONS, RESUME_ON_ELAPSED
from maistro.runs.model import Run, RunStatus
from maistro.runs.recovery_events import RecoveryEventSink
from maistro.runs.store import RunStore
from maistro.runtime import ExecutionRuntime

from . import executor as traversal
from .attempt_executor import LiveAttemptOwned, NodeResolver, resume_durable_graph
from .launch import launch_state_from_run
from .protocol import DurableRunStore
from .types import DurableRunRecord

QueuedRunPredicate = Callable[[Run], bool]
QueuedNodeResolverFactory = Callable[[Run], NodeResolver]


@runtime_checkable
class PersistenceReconciler(Protocol):
    async def reconcile_persistence(self, *, limit: int = 100) -> int: ...


async def _reconcile_if_supported(store: DurableRunStore, *, limit: int) -> None:
    if isinstance(store, PersistenceReconciler):
        await store.reconcile_persistence(limit=limit)


_RESUME_ELIGIBLE_STATUSES = frozenset({RunStatus.WAITING, RunStatus.RUNNING})


def _is_resume_due(record: DurableRunRecord, moment: datetime) -> bool:
    """Report whether `record` is in a resumable status with an elapsed wait."""
    if record.run.status not in _RESUME_ELIGIBLE_STATUSES:
        return False
    return record.resume_at is not None and record.resume_at <= moment


def _answer_gated_pause(record: DurableRunRecord) -> tuple[str, str] | None:
    """Return one due answer-gated pause and its resume condition.

    A due ``resume_at`` on an answer-gated dispatch is a deadline, not permission
    to execute the dispatch again. The timer waker writes a timeout answer first;
    the normal Graph Attempt path then consumes that answer exactly once.
    """
    graph_state = getattr(record, "graph_state", None)
    if graph_state is None:
        return None
    pauses = graph_state.metadata.get("pauses", {})
    if not isinstance(pauses, Mapping):
        return None
    for node_id in graph_state.active_node_ids:
        pause = pauses.get(node_id)
        if not isinstance(pause, Mapping):
            continue
        metadata = pause.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        reason = str(metadata.get("paused_reason") or "")
        condition = PAUSE_RESUME_CONDITIONS.get(reason)
        if condition is not None and condition != RESUME_ON_ELAPSED:
            return str(node_id), reason
    return None


async def _is_still_resume_due(
    store: DurableRunStore,
    run_id: str,
    moment: datetime,
) -> bool:
    """Re-read `run_id` and report whether it is still due for a resume."""
    current = await store.get(run_id)
    return current is not None and _is_resume_due(current, moment)


async def _timeout_answer_gated_pause(
    store: DurableRunStore,
    candidate: DurableRunRecord,
    *,
    node_id: str,
    reason: str,
    moment: datetime,
) -> DurableRunRecord | None:
    """Write a deadline result before re-entering an answer-gated node."""
    try:
        return await store.submit_external_result(
            candidate.run_id,
            node_id,
            {
                "status": "timed_out",
                "timed_out": True,
                "error": f"{reason} deadline elapsed",
            },
            at=moment,
        )
    except (KeyError, ValueError):
        refreshed = await store.get(candidate.run_id)
        if refreshed is None or not _is_resume_due(refreshed, moment):
            return None
        raise


async def resume_due_graph_runs(
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver: NodeResolver | None = None,
    node_resolver_factory: QueuedNodeResolverFactory | None = None,
    runtime: ExecutionRuntime | None = None,
    now: datetime | None = None,
    limit: int = 100,
    eligible: QueuedRunPredicate | None = None,
    events: RecoveryEventSink | None = None,
) -> int:
    """Resume elapsed durable Graph waits or expired recovery claims.

    Exactly one of ``node_resolver`` (one resolver answers every candidate) or
    ``node_resolver_factory`` (the resolver is rebuilt from each candidate's
    own durable Run facts) must be supplied. The factory is the shape a
    production wakeup consumer needs: which node implementation may execute a
    resumed Graph is recorded on the Run itself, not in the waking process's
    memory (#62, #837).

    ``eligible`` is the same ownership guard ``recover_queued_graph_runs``
    takes: a tick that wakes due continuations without it would execute
    another consumer's paused work with this process's resolvers. The guard
    reads the Run, and the optimistic continuation version plus the canonical
    Attempt lease/fence still decide admission regardless of what it says.

    ``events`` carries the resume's crash dispositions onto the canonical
    Event stream when the caller provides a sink.
    """
    if limit <= 0:
        return 0
    _require_resolver_choice(node_resolver, node_resolver_factory)
    resolver_for = _per_run_resolver(node_resolver, node_resolver_factory)

    await _reconcile_if_supported(store, limit=limit)
    moment = now if now is not None else datetime.now(UTC)
    candidates = await store.list_due(now=moment, limit=limit)
    resumed = 0

    for candidate in candidates:
        if not _is_resume_due(candidate, moment):
            continue
        if eligible is not None and not eligible(candidate.run):
            continue
        answer_gated = _answer_gated_pause(candidate)
        if answer_gated is not None:
            node_id, reason = answer_gated
            resumed_candidate = await _timeout_answer_gated_pause(
                store,
                candidate,
                node_id=node_id,
                reason=reason,
                moment=moment,
            )
            if resumed_candidate is None:
                continue
            candidate = resumed_candidate
        try:
            await resume_durable_graph(
                candidate.run_id,
                store=store,
                node_resolver=resolver_for(candidate.run),
                runtime=runtime,
                run_store=run_store,
                events=events,
            )
        except LiveAttemptOwned:
            continue
        except (KeyError, ValueError):
            # Only a record still due after the failure is a real error; a
            # record another actor already moved on is settled, not resumed.
            if not await _is_still_resume_due(store, candidate.run_id, moment):
                continue
            raise
        resumed += 1

    return resumed


def _initial_queued_record(run: Run) -> DurableRunRecord:
    """Reconstruct checkpoint 1 from the immutable admission snapshot."""
    graph = run.graph.materialize()
    initial_inputs, blackboard_metadata = launch_state_from_run(run)
    state = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=(traversal._entry_node(graph),),
        blackboard_snapshot={
            "task_objective": graph.name,
            "metadata": blackboard_metadata,
            "node_annotations": {},
        },
        metadata={"initial_inputs": initial_inputs, "hitl_answers": {}},
    )
    return DurableRunRecord(run=run, graph_state=state, version=1)


async def _claim_initial_continuation(
    store: DurableRunStore,
    run: Run,
) -> DurableRunRecord | None:
    current = await store.get(run.run_id)
    if current is not None:
        return current

    try:
        await store.create(_initial_queued_record(run))
    except Exception:
        current = await store.get(run.run_id)
        if current is None:
            raise
        return None

    current = await store.get(run.run_id)
    if current is None:  # pragma: no cover - persistence contract breach
        raise RuntimeError(f"initial continuation for Run {run.run_id!r} disappeared after create")
    return current


async def _resume_queued_candidate(
    run: Run,
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver_factory: QueuedNodeResolverFactory,
    runtime: ExecutionRuntime | None,
    events: RecoveryEventSink | None,
) -> bool:
    current = await _claim_initial_continuation(store, run)
    if current is None or current.run.status is not RunStatus.QUEUED:
        return False

    try:
        await resume_durable_graph(
            run.run_id,
            store=store,
            node_resolver=node_resolver_factory(run),
            runtime=runtime,
            run_store=run_store,
            events=events,
        )
    except LiveAttemptOwned:
        return False
    except (KeyError, ValueError):
        latest = await store.get(run.run_id)
        if latest is None:
            raise
        if latest.run.status is not RunStatus.QUEUED:
            return False
        raise
    return True


async def recover_queued_graph_runs(
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver_factory: QueuedNodeResolverFactory,
    eligible: QueuedRunPredicate,
    runtime: ExecutionRuntime | None = None,
    limit: int = 100,
    events: RecoveryEventSink | None = None,
) -> int:
    """Recover admitted durable Graph Runs around checkpoint 1.

    Checkpoint 1 is reconstructed exclusively from durable Run facts. New
    non-empty launch state is required to be snapshotted in Run provenance by
    the public admission helper before physical execution can start, so this
    recovery path never substitutes empty inputs for work the caller actually
    admitted.

    ``events`` carries each recovery's crash dispositions onto the canonical
    Event stream when the caller provides a sink.
    """
    if limit <= 0:
        return 0

    await _reconcile_if_supported(store, limit=limit)
    candidates = await run_store.list_by_status(RunStatus.QUEUED, limit=limit)
    recovered = 0
    for run in candidates:
        if eligible(run) and await _resume_queued_candidate(
            run,
            store=store,
            run_store=run_store,
            node_resolver_factory=node_resolver_factory,
            runtime=runtime,
            events=events,
        ):
            recovered += 1
    return recovered


def _require_resolver_choice(
    node_resolver: NodeResolver | None,
    node_resolver_factory: QueuedNodeResolverFactory | None,
) -> None:
    """Enforce the exactly-one resolver contract the wakeup tick documents."""
    if (node_resolver is None) == (node_resolver_factory is None):
        raise ValueError(
            "resume_due_graph_runs requires exactly one of node_resolver or node_resolver_factory"
        )


def _per_run_resolver(
    node_resolver: NodeResolver | None,
    node_resolver_factory: QueuedNodeResolverFactory | None,
) -> Callable[[Run], NodeResolver]:
    """Fold the two resolver shapes into one per-Run lookup.

    A single resolver answers every Run; a factory answers each from its own
    durable facts. The tick should not have to care which shape its caller chose.
    """
    if node_resolver is not None:
        return lambda _run: node_resolver
    if node_resolver_factory is not None:
        return node_resolver_factory
    raise ValueError(  # pragma: no cover - _require_resolver_choice ran first
        "resume_due_graph_runs requires exactly one of node_resolver or node_resolver_factory"
    )


__all__ = ["recover_queued_graph_runs", "resume_due_graph_runs"]
