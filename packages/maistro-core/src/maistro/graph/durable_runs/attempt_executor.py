"""Canonical durable Graph execution through physical Attempts.

Traversal semantics stay in :mod:`maistro.graph.durable_runs.executor`. This
module owns the execution firewall: every frontier NodeRun is physically
executed by ``AttemptExecutionService -> ExecutionRuntime`` before the proven
Graph folding/routing helpers advance logical state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from maistro.graph.definitions import Graph
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes.base import NodeContext, NodeResult
from maistro.runs.execution import AttemptExecutionService
from maistro.runs.lifecycle import transition_run
from maistro.runs.model import Attempt, AttemptStatus, NodeRun, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler, CancellationCause
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

from . import executor as traversal
from .authoritative_fold import fold_authoritative_frontier
from .execution_store import DurableRunExecutionStore
from .protocol import DurableRunStore
from .types import DurableRunRecord

NodeResolver = traversal.NodeResolver


async def run_durable_graph(
    graph: Graph,
    *,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    inputs: dict[str, Any] | None = None,
    actor_principal_id: str | None = None,
    run_id: str | None = None,
    runtime: ExecutionRuntime | None = None,
    parent_run_id: str | None = None,
    parent_node_run_id: str | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> DurableRunRecord:
    """Start a durable Graph whose physical node work crosses the Attempt firewall.

    ``parent_run_id``/``parent_node_run_id`` make the launched Run a child of
    the Run (and NodeRun) that produced it — delegation and sub-graph work
    say "work is happening" as a child Run, not a second lifecycle.

    ``provenance`` records what admitted the work, and is accepted here as
    well as in the traversal executor so the two entry points cannot disagree
    about whether a Run remembers where it came from (#145).
    """
    run = traversal._new_run(
        graph,
        run_id=run_id,
        actor_principal_id=actor_principal_id,
        parent_run_id=parent_run_id,
        parent_node_run_id=parent_node_run_id,
        provenance=provenance,
    )
    state = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=(traversal._entry_node(graph),),
        blackboard_snapshot={
            "task_objective": graph.name,
            "metadata": {},
            "node_annotations": {},
        },
        metadata={"initial_inputs": dict(inputs or {}), "hitl_answers": {}},
    )
    record = DurableRunRecord(run=run, graph_state=state, version=1)
    await store.create(record)
    return await _walk(
        record,
        store=store,
        node_resolver=node_resolver,
        runtime=runtime or PythonExecutionRuntime(),
    )


async def resume_durable_graph(
    run_id: str,
    *,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    runtime: ExecutionRuntime | None = None,
) -> DurableRunRecord:
    """Resume after reconciling persisted physical evidence before redispatch."""
    record = await store.get(run_id)
    if record is None:
        raise KeyError(f"no such run: {run_id!r}")
    if record.run.status is RunStatus.PAUSED:
        raise ValueError("HITL run must receive an answer before resume")
    if record.run.status not in {
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.WAITING,
    }:
        raise ValueError(f"cannot resume run in status {record.run.status!r}")

    record = await _reconcile_orphaned_attempts(record, store=store)

    run = record.run
    if run.status in {RunStatus.WAITING, RunStatus.QUEUED}:
        run = transition_run(run, RunStatus.RUNNING)
    record = await traversal._checkpoint(
        record,
        store=store,
        run=run,
        resume_at=None,
    )
    return await _walk(
        record,
        store=store,
        node_resolver=node_resolver,
        runtime=runtime or PythonExecutionRuntime(),
    )


async def _reconcile_orphaned_attempts(
    record: DurableRunRecord,
    *,
    store: DurableRunStore,
) -> DurableRunRecord:
    """Terminalize process-lost active Attempts and reconcile their NodeRuns."""
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)
    lifecycle = AttemptLifecycleReconciler(execution_store)
    active = tuple(
        attempt
        for attempt in record.attempts
        if attempt.status in {AttemptStatus.CREATED, AttemptStatus.RUNNING}
    )
    for attempt in active:
        terminal = await execution_store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.CANCELLED,
            error="orphaned physical Attempt recovered after process loss",
        )
        # RECOVERED, stated rather than defaulted. This cancellation is
        # bookkeeping — the process died and the physical record is being closed
        # so a *fresh* Attempt can run — so the node must stay parked and owed.
        # Terminalizing it would make crash recovery destroy the work it exists
        # to resume (#230).
        await lifecycle.reconcile(terminal, cancellation=CancellationCause.RECOVERED)
    latest = await store.get(record.run_id)
    if latest is None:
        raise KeyError(f"no such run: {record.run_id!r}")
    return latest


def _requires_hitl_redispatch(
    record: DurableRunRecord,
    node_id: str,
    result: NodeResult,
) -> bool:
    """Return whether accepted paused evidence must yield to newly submitted HITL input."""
    return (
        result.status == "paused"
        and traversal._is_human_pause(result)
        and node_id in record.hitl_answers
    )


async def _walk(
    record: DurableRunRecord,
    *,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    runtime: ExecutionRuntime,
    max_steps: int = 256,
) -> DurableRunRecord:
    """Execute persisted frontiers through Attempts, then fold Graph semantics."""
    graph = record.run.graph.materialize()
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)
    execution_service = AttemptExecutionService(store=execution_store, runtime=runtime)
    steps = 0

    while record.graph_state.active_node_ids and steps < max_steps:
        steps += 1
        record = await _walk_frontier(
            record,
            graph=graph,
            store=store,
            node_resolver=node_resolver,
            execution_service=execution_service,
            execution_store=execution_store,
        )
        if record.run.status is not RunStatus.RUNNING:
            return record

    return await traversal._finish_walk(
        record,
        store=store,
        max_steps=max_steps,
    )


async def _walk_frontier(
    record: DurableRunRecord,
    *,
    graph: Graph,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    execution_service: AttemptExecutionService,
    execution_store: DurableRunExecutionStore,
) -> DurableRunRecord:
    frontier = record.graph_state.active_node_ids
    unknown = next(
        (node_id for node_id in frontier if traversal._node_spec(graph, node_id) is None),
        None,
    )
    if unknown is not None:
        return await traversal._mark_failed(
            record,
            error_code="UnknownNode",
            error_message=f"node_id={unknown!r} not present in Graph",
            store=store,
        )

    record, node_runs = await traversal._ensure_frontier_node_runs(
        record,
        frontier,
        store=store,
    )
    try:
        items = await _execute_frontier(
            record,
            graph,
            frontier,
            node_runs,
            node_resolver=node_resolver,
            execution_service=execution_service,
            execution_store=execution_store,
        )
    except asyncio.CancelledError:
        await asyncio.shield(_persist_cancelled_run(record.run_id, store=store))
        raise
    except Exception as exc:
        latest = await _reload_record(record.run_id, store=store, cause=exc)
        return await traversal._mark_failed(
            latest,
            error_code="PhysicalExecutionError",
            error_message=str(exc) or type(exc).__name__,
            store=store,
        )

    latest = await _reload_record(record.run_id, store=store)
    return await fold_authoritative_frontier(
        latest,
        graph,
        items,
        store=store,
    )


async def _reload_record(
    run_id: str,
    *,
    store: DurableRunStore,
    cause: BaseException | None = None,
) -> DurableRunRecord:
    latest = await store.get(run_id)
    if latest is None:
        if cause is None:
            raise KeyError(f"no such run: {run_id!r}")
        raise KeyError(f"no such run: {run_id!r}") from cause
    return latest


async def _persist_cancelled_run(
    run_id: str,
    *,
    store: DurableRunStore,
) -> DurableRunRecord:
    latest = await store.get(run_id)
    if latest is None:
        raise KeyError(f"no such run: {run_id!r}")
    latest = traversal._settle_open_node_runs(latest, RunStatus.CANCELLED)
    run = traversal._running_run(latest.run)
    if run.status is RunStatus.RUNNING:
        run = transition_run(
            run,
            RunStatus.CANCELLED,
            error="durable Graph execution cancelled",
        )
    state = traversal._replace_state(
        latest.graph_state,
        active_node_ids=(),
    )
    return await traversal._checkpoint(
        latest,
        store=store,
        run=run,
        graph_state=state,
        resume_at=None,
    )


async def _execute_frontier(
    record: DurableRunRecord,
    graph: Graph,
    frontier: tuple[str, ...],
    node_runs: tuple[NodeRun, ...],
    *,
    node_resolver: NodeResolver,
    execution_service: AttemptExecutionService,
    execution_store: DurableRunExecutionStore,
) -> tuple[Any, ...]:
    """Execute/recover one complete frontier concurrently through canonical Attempts."""
    prepared: list[tuple[str, Any, NodeRun, NodeContext, Any, dict[str, Any]]] = []
    for node_id, node_run in zip(frontier, node_runs, strict=True):
        spec = traversal._node_spec(graph, node_id)
        assert spec is not None
        ctx = traversal._build_ctx(record, node_id)
        node = node_resolver(node_id, graph)
        inputs = traversal._resolve_inputs(graph, record, node_run, spec)
        prepared.append((node_id, spec, node_run, ctx, node, inputs))

    async def execute_one(
        node_id: str,
        spec: Any,
        node_run: NodeRun,
        ctx: NodeContext,
        node: Any,
        inputs: dict[str, Any],
    ) -> Any:
        prior_completion_accepted = False
        attempts = await execution_store.list_attempts(node_run.node_run_id)
        if attempts and attempts[-1].status is AttemptStatus.COMPLETED:
            persisted_result = NodeResult.model_validate(attempts[-1].result)
            prior_completion_accepted = _requires_hitl_redispatch(
                record,
                node_id,
                persisted_result,
            )
            if not prior_completion_accepted:
                return traversal._FrontierItem(
                    node_id,
                    spec,
                    node_run,
                    ctx,
                    persisted_result,
                )

        raw_result: NodeResult | None = None

        async def executor(work_item: Any, execution_context: Any) -> NodeResult:
            nonlocal raw_result
            result: NodeResult = await node.run(work_item, execution_context)
            raw_result = result
            return result

        def context_for_attempt(attempt: Attempt, base: Any) -> NodeContext:
            if not isinstance(base, NodeContext):
                raise TypeError("durable Graph execution requires NodeContext")
            return base.model_copy(
                update={
                    "node_run_id": node_run.node_run_id,
                    "attempt_id": attempt.attempt_id,
                }
            )

        await execution_service.execute(
            node_run.node_run_id,
            inputs,
            ctx,
            executor=executor,
            executor_id=str(getattr(node, "kind", None) or spec.node_type or node_id),
            reconcile_logical=False,
            context_factory=context_for_attempt,
            prior_completion_accepted=prior_completion_accepted,
        )
        if raw_result is None:
            raise RuntimeError(f"node {node_id!r} completed without a NodeResult")
        return traversal._FrontierItem(
            node_id,
            spec,
            node_run,
            ctx,
            raw_result,
        )

    return tuple(
        await asyncio.gather(
            *(
                execute_one(node_id, spec, node_run, ctx, node, inputs)
                for node_id, spec, node_run, ctx, node, inputs in prepared
            )
        )
    )


__all__ = ["NodeResolver", "resume_durable_graph", "run_durable_graph"]
