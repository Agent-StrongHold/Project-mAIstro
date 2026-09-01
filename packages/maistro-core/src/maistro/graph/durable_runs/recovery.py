"""Bounded production recovery for persisted canonical Graph work (#837).

This module does not own a queue, timer, Run lifecycle, or execution policy. It
provides recovery ticks over the canonical Run spine and durable Graph
continuations. Physical work still crosses the canonical Attempt/lease/fence
boundary in :mod:`attempt_executor`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import Run, RunStatus
from maistro.runs.store import RunStore
from maistro.runtime import ExecutionRuntime

from . import executor as traversal
from .attempt_executor import LiveAttemptOwned, NodeResolver, resume_durable_graph
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


async def resume_due_graph_runs(
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver: NodeResolver,
    runtime: ExecutionRuntime | None = None,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    """Resume elapsed durable Graph waits or expired recovery claims."""
    if limit <= 0:
        return 0

    await _reconcile_if_supported(store, limit=limit)
    moment = now if now is not None else datetime.now(UTC)
    candidates = await store.list_due(now=moment, limit=limit)
    resumed = 0

    for candidate in candidates:
        if candidate.run.status is RunStatus.PAUSED:
            continue
        if candidate.run.status not in {RunStatus.WAITING, RunStatus.RUNNING}:
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
        except LiveAttemptOwned:
            continue
        except (KeyError, ValueError):
            current = await store.get(candidate.run_id)
            if current is None:
                continue
            if (
                current.run.status not in {RunStatus.WAITING, RunStatus.RUNNING}
                or current.resume_at is None
                or current.resume_at > moment
            ):
                continue
            raise
        resumed += 1

    return resumed


def _initial_queued_record(run: Run) -> DurableRunRecord:
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
) -> int:
    """Recover admitted durable Graph Runs around checkpoint 1."""
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
        ):
            recovered += 1
    return recovered


__all__ = ["recover_queued_graph_runs", "resume_due_graph_runs"]
