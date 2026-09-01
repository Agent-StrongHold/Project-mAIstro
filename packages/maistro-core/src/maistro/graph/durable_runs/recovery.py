"""Bounded production recovery for persisted canonical Graph work (#837).

This module does not own a queue, timer, Run lifecycle, or execution policy. It
provides recovery ticks over the canonical Run spine and durable Graph
continuations. Physical work still crosses the canonical Attempt/lease/fence
boundary in :mod:`attempt_executor`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import Run, RunStatus
from maistro.runs.store import RunStore
from maistro.runtime import ExecutionRuntime

from . import executor as traversal
from .attempt_executor import NodeResolver, resume_durable_graph
from .protocol import DurableRunStore
from .types import DurableRunRecord

QueuedRunPredicate = Callable[[Run], bool]
QueuedNodeResolverFactory = Callable[[Run], NodeResolver]


async def resume_due_graph_runs(
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver: NodeResolver,
    runtime: ExecutionRuntime | None = None,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    """Resume at most ``limit`` elapsed durable Graph waits.

    ``list_due`` may also surface overdue ``PAUSED`` records because the same
    persisted deadline is useful to HITL timeout/cancel reconciliation. A clock
    must never manufacture a human answer, so this executor only consumes
    ``WAITING`` records. ``resume_durable_graph`` then reconciles orphaned
    Attempts and refuses work protected by a live execution lease before any
    redispatch.

    Across replicas, the resume seam's first write is the continuation's
    optimistic ``version + 1`` checkpoint. If another worker wins between this
    indexed read and that checkpoint, re-read canonical state: an ineligible
    record means the other worker legitimately moved it, while a still-eligible
    record means the error was real and must remain visible.
    """
    if limit <= 0:
        return 0

    moment = now if now is not None else datetime.now(UTC)
    candidates = await store.list_due(now=moment, limit=limit)
    resumed = 0

    for candidate in candidates:
        if candidate.run.status is not RunStatus.WAITING:
            continue
        if candidate.resume_at is None or candidate.resume_at > moment:
            continue
        try:
            await resume_durable_graph(
                candidate.run_id,
                store=store,
                node_resolver=node_resolver,
                runtime=runtime,
                run_store=run_store,
            )
        except (KeyError, ValueError):
            current = await store.get(candidate.run_id)
            if current is None:
                continue
            if (
                current.run.status is not RunStatus.WAITING
                or current.resume_at is None
                or current.resume_at > moment
            ):
                continue
            raise
        resumed += 1

    return resumed


def _initial_queued_record(run: Run) -> DurableRunRecord:
    """Build the first continuation for an already-admitted canonical Graph Run."""
    graph = run.graph.materialize()
    state = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=(traversal._entry_node(graph),),
        blackboard_snapshot={
            "task_objective": graph.name,
            "metadata": {},
            "node_annotations": {},
        },
        metadata={"initial_inputs": {}, "hitl_answers": {}},
    )
    return DurableRunRecord(run=run, graph_state=state, version=1)


async def _claim_initial_continuation(
    store: DurableRunStore,
    run: Run,
) -> DurableRunRecord | None:
    """Return the continuation this worker may resume, or None when a peer won bootstrap."""
    current = await store.get(run.run_id)
    if current is not None:
        return current

    try:
        await store.create(_initial_queued_record(run))
    except Exception:
        # SQLite, asyncpg, and in-memory stores expose different duplicate-row
        # exceptions. The authoritative distinction is whether a continuation
        # now exists. If it does, another replica won checkpoint 1 and owns this
        # tick. If it does not, this was a real persistence failure.
        current = await store.get(run.run_id)
        if current is None:
            raise
        return None

    current = await store.get(run.run_id)
    if current is None:  # pragma: no cover - persistence contract breach
        raise RuntimeError(
            f"initial continuation for Run {run.run_id!r} disappeared after create"
        )
    return current


async def _resume_queued_candidate(
    run: Run,
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver_factory: QueuedNodeResolverFactory,
    runtime: ExecutionRuntime | None,
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
        )
    except (KeyError, ValueError):
        latest = await store.get(run.run_id)
        if latest is None:
            raise
        if latest.run.status is not RunStatus.QUEUED:
            # Another worker advanced the optimistic continuation version and
            # owns execution. Do not redispatch behind it.
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
) -> int:
    """Recover admitted durable Graph Runs that died before or just after checkpoint 1.

    This closes the admission-to-first-checkpoint crash window without adding a
    second scheduler. Candidate identity and lifecycle come only from
    ``RunStore``. Callers must provide an explicit eligibility predicate because
    ``QUEUED`` is shared by other canonical consumers; recovery must never steal
    work merely because it is queued.

    Two persisted crash shapes are supported:

    * ``QUEUED`` Run with no continuation: create checkpoint 1 as the atomic
      bootstrap claim, then resume through the normal durable executor.
    * ``QUEUED`` Run with checkpoint 1 already present: resume it directly.

    ``store.create`` is the cross-replica bootstrap fence. Continuation stores
    enforce one row per canonical Run. If another replica wins that insert, the
    loser observes the row and does not execute it. If the winner dies after the
    insert but before dispatch, a later recovery tick sees the existing QUEUED
    continuation and resumes it. Existing continuation resumes use the normal
    optimistic checkpoint version as their replica race fence.
    """
    if limit <= 0:
        return 0

    candidates = await run_store.list_by_status(RunStatus.QUEUED, limit=limit)
    recovered = 0
    for run in candidates:
        if eligible(run) and await _resume_queued_candidate(
            run,
            store=store,
            run_store=run_store,
            node_resolver_factory=node_resolver_factory,
            runtime=runtime,
        ):
            recovered += 1
    return recovered


__all__ = ["recover_queued_graph_runs", "resume_due_graph_runs"]
