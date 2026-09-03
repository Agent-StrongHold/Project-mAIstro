"""Canonical durable Graph execution through physical Attempts.

Traversal semantics stay in :mod:`maistro.graph.durable_runs.executor`. This
module owns the execution firewall: every frontier NodeRun is physically
executed by ``AttemptExecutionService -> ExecutionRuntime`` before the proven
Graph folding/routing helpers advance logical state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from maistro.graph.definitions import Graph
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes.base import NodeContext, NodeResult
from maistro.observability.correlation import bind_execution_context
from maistro.runs.execution import AttemptExecutionService
from maistro.runs.lifecycle import lease_is_expired, transition_path, transition_run
from maistro.runs.model import Attempt, AttemptStatus, NodeRun, Run, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler, CancellationCause
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

from . import executor as traversal
from .authoritative_fold import fold_authoritative_frontier
from .execution_store import DurableRunExecutionStore
from .protocol import DurableRunStore
from .spine import mirror_lifecycle
from .types import DurableRunRecord

NodeResolver = traversal.NodeResolver

# Durable Graph execution always opts into the canonical lease/fence recovery
# contract. The claim is deliberately longer than one lease renewal window:
# continuation recovery may notice an elapsed claim while a long-running
# Attempt is still alive, but the Attempt lease is the stronger physical-work
# proof and makes that recovery worker yield.
GRAPH_ATTEMPT_LEASE_TTL = timedelta(seconds=30)
GRAPH_RECOVERY_CLAIM_TTL = timedelta(seconds=60)


class LiveAttemptOwned(RunIntegrityError):
    """A different worker still owns live physical work for this Graph Run."""


async def _validated_admitted_run(
    graph: Graph,
    *,
    run_store: RunStore,
    run_id: str,
) -> Run:
    """Return the admitted canonical Run without starting it.

    Checkpoint 1 is the durable bootstrap claim. Moving the Run to RUNNING
    before that row exists recreates the exact admission-to-continuation crash
    window recovery is meant to close.
    """
    admitted = await run_store.get_run(run_id)
    if admitted is None:
        raise RunIntegrityError(
            f"pinned run_id {run_id!r} is not on the canonical spine; "
            "durable graph execution consumes an admitted Run"
        )
    if admitted.graph.content_hash != graph.content_hash:
        raise RunIntegrityError(
            f"pinned Run {run_id!r} was admitted for a different Graph; "
            "the supplied Graph does not match the admitted snapshot"
        )
    if admitted.workspace_id != graph.workspace_id or admitted.project_id != graph.project_id:
        raise RunIntegrityError(
            f"pinned Run {run_id!r} is scoped to "
            f"{admitted.workspace_id!r}/{admitted.project_id!r}, not "
            f"{graph.workspace_id!r}/{graph.project_id!r}"
        )
    if admitted.status is not RunStatus.QUEUED:
        raise RunIntegrityError(
            f"pinned Run {run_id!r} must still be queued before its first "
            f"durable Graph checkpoint, not {admitted.status.value!r}"
        )
    return admitted


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
    blackboard_metadata: Mapping[str, Any] | None = None,
    run_store: RunStore | None = None,
) -> DurableRunRecord:
    """Start a durable Graph whose physical node work crosses the Attempt firewall.

    ``parent_run_id``/``parent_node_run_id`` make the launched Run a child of
    the Run (and NodeRun) that produced it — delegation and sub-graph work
    say "work is happening" as a child Run, not a second lifecycle.

    ``provenance`` records what admitted the work, and is accepted here as
    well as in the traversal executor so the two entry points cannot disagree
    about whether a Run remembers where it came from (#145).

    ``blackboard_metadata`` seeds the child's blackboard metadata. A parent
    dispatching a sub-graph threads facts the child cannot derive — the
    recursion depth its own `synth_depth` cap enforces (#520) — without the
    parent's whole blackboard leaking across the Run boundary.

    ``run_store`` converges the Run's identity onto the canonical spine (#44,
    ADR-082826-d9f5). With it, checkpoint 1 is persisted while the already
    admitted Run is still QUEUED; the canonical resume seam then claims it.
    That ordering makes process death before/after the continuation write
    rediscoverable. Without a spine, the pre-convergence in-memory mint is
    unchanged.
    """
    if run_store is not None:
        run = await _validated_admitted_run(
            graph,
            run_store=run_store,
            run_id=traversal._require_admitted(run_id),
        )
    else:
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
            "metadata": dict(blackboard_metadata or {}),
            "node_annotations": {},
        },
        metadata={"initial_inputs": dict(inputs or {}), "hitl_answers": {}},
    )
    record = DurableRunRecord(run=run, graph_state=state, version=1)
    await store.create(record)

    if run_store is not None:
        return await resume_durable_graph(
            run.run_id,
            store=store,
            node_resolver=node_resolver,
            runtime=runtime,
            run_store=run_store,
        )
    return await _walk(
        record,
        store=store,
        node_resolver=node_resolver,
        runtime=runtime or PythonExecutionRuntime(),
        run_store=None,
    )


async def resume_durable_graph(
    run_id: str,
    *,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    runtime: ExecutionRuntime | None = None,
    run_store: RunStore | None = None,
) -> DurableRunRecord:
    """Claim and resume persisted Graph work through canonical physical evidence."""
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

    spine = await traversal._canonical_spine(record, run_store)
    record = await _reconcile_orphaned_attempts(record, store=store, run_store=spine)

    claim_until = datetime.now(UTC) + GRAPH_RECOVERY_CLAIM_TTL
    record = await traversal._checkpoint(
        record,
        store=store,
        resume_at=claim_until,
    )

    run = record.run
    if run.status in {RunStatus.WAITING, RunStatus.QUEUED}:
        stepped: Run | None = None
        if spine is not None:
            canonical = await spine.get_run(run.run_id)
            if canonical is not None:
                for step in transition_path(canonical.status, RunStatus.RUNNING):
                    canonical = await spine.transition_run(run.run_id, step)
                stepped = canonical
        if stepped is None:
            # No spine row to walk stepwise (no spine, or the row was purged
            # mid-resume): advance the record's own lifecycle instead, the
            # pre-convergence behavior, rather than attribute-error here.
            record = traversal._replace_record(
                record,
                run=transition_run(run, RunStatus.RUNNING),
            )
        else:
            record = traversal._replace_record(record, run=stepped)

    return await _walk(
        record,
        store=store,
        node_resolver=node_resolver,
        runtime=runtime or PythonExecutionRuntime(),
        run_store=spine,
    )


async def _reconcile_orphaned_attempts(
    record: DurableRunRecord,
    *,
    store: DurableRunStore,
    run_store: RunStore | None = None,
) -> DurableRunRecord:
    """Terminalize process-lost active Attempts and reconcile their NodeRuns."""
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id, run_store=run_store)
    lifecycle = AttemptLifecycleReconciler(execution_store)
    active = tuple(
        attempt
        for attempt in record.attempts
        if attempt.status in {AttemptStatus.CREATED, AttemptStatus.RUNNING}
    )
    now = datetime.now(UTC)
    for attempt in active:
        lease = attempt.execution_lease
        if lease is not None and not lease_is_expired(attempt, now):
            raise LiveAttemptOwned(
                f"cannot resume run {record.run_id!r}: Attempt "
                f"{attempt.attempt_id!r} holds a live execution lease "
                f"(holder {lease.holder!r}); a demonstrably live worker owns "
                "this work"
            )

    reclaimed = await execution_store.reclaim_expired_attempts(now=now)
    for attempt in reclaimed:
        await lifecycle.reconcile(attempt, cancellation=CancellationCause.RECOVERED)

    for attempt in active:
        if attempt.execution_lease is not None:
            continue
        terminal = await execution_store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.CANCELLED,
            error="orphaned physical Attempt recovered after process loss",
        )
        await lifecycle.reconcile(terminal, cancellation=CancellationCause.RECOVERED)
    latest = await store.get(record.run_id)
    if latest is None:
        raise KeyError(f"no such run: {record.run_id!r}")
    return latest


def _requires_continuation_redispatch(
    record: DurableRunRecord,
    node_id: str,
    result: NodeResult,
) -> bool:
    """Whether accepted pause evidence now requires a fresh physical try."""
    if result.status != "paused":
        return False
    if traversal._is_human_pause(result):
        return node_id in record.hitl_answers
    return result.resume_at is not None and result.resume_at <= datetime.now(UTC)


async def _walk(
    record: DurableRunRecord,
    *,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    runtime: ExecutionRuntime,
    max_steps: int = 256,
    run_store: RunStore | None = None,
) -> DurableRunRecord:
    """Execute persisted frontiers through Attempts, then fold Graph semantics."""
    graph = record.run.graph.materialize()
    spine = await traversal._canonical_spine(record, run_store)
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id, run_store=spine)
    execution_service = AttemptExecutionService(
        store=execution_store,
        runtime=runtime,
        lease_ttl=GRAPH_ATTEMPT_LEASE_TTL,
    )
    steps = 0

    # The Run record is already in hand here, so binding its Workspace and
    # Project costs no read — the exact "outer bind supplies them for free
    # where they are known" case ADR-083026-1cb1 reserved this seam for. Until
    # now nothing on any real path bound them at all: `execute_node` holds only
    # `run_id`, and the HTTP seam holds only `request_id`, so an event emitted
    # inside a durable execution filled `project_id` only if its producer set
    # it by hand, and a log line named a Run with no Workspace (#63).
    with bind_execution_context(
        run_id=record.run_id,
        workspace_id=record.run.workspace_id,
        project_id=record.run.project_id,
    ):
        return await _walk_until_settled(
            record,
            graph=graph,
            store=store,
            node_resolver=node_resolver,
            execution_service=execution_service,
            execution_store=execution_store,
            spine=spine,
            max_steps=max_steps,
            steps=steps,
        )


async def _walk_until_settled(
    record: DurableRunRecord,
    *,
    graph: Graph,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    execution_service: AttemptExecutionService,
    execution_store: DurableRunExecutionStore,
    spine: RunStore | None,
    max_steps: int,
    steps: int,
) -> DurableRunRecord:
    """Walk frontiers until the Run settles or `max_steps` is spent."""
    while record.graph_state.active_node_ids and steps < max_steps:
        steps += 1
        record = await _walk_frontier(
            record,
            graph=graph,
            store=store,
            node_resolver=node_resolver,
            execution_service=execution_service,
            execution_store=execution_store,
            run_store=spine,
        )
        await mirror_lifecycle(record, run_store=spine)
        if record.run.status is not RunStatus.RUNNING:
            return record

    record = await traversal._finish_walk(
        record,
        store=store,
        max_steps=max_steps,
    )
    await mirror_lifecycle(record, run_store=spine)
    return record


async def _walk_frontier(
    record: DurableRunRecord,
    *,
    graph: Graph,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    execution_service: AttemptExecutionService,
    execution_store: DurableRunExecutionStore,
    run_store: RunStore | None = None,
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
        run_store=run_store,
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
        await asyncio.shield(
            _persist_cancelled_run(record.run_id, store=store, run_store=run_store)
        )
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
    run_store: RunStore | None = None,
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
    cancelled = await traversal._checkpoint(
        latest,
        store=store,
        run=run,
        graph_state=state,
        resume_at=None,
    )
    await mirror_lifecycle(cancelled, run_store=run_store)
    return cancelled


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
            prior_completion_accepted = _requires_continuation_redispatch(
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


__all__ = [
    "GRAPH_ATTEMPT_LEASE_TTL",
    "GRAPH_RECOVERY_CLAIM_TTL",
    "LiveAttemptOwned",
    "NodeResolver",
    "resume_durable_graph",
    "run_durable_graph",
]
