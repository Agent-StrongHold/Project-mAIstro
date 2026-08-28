"""Concurrent durable execution for canonical Graph frontiers.

Run owns universal lifecycle. GraphExecutionState owns traversal facts. This
module executes every node in the active frontier concurrently while keeping
NodeRun creation, result folding, routing decisions, persistence order, and
fan-in deterministic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from maistro.graph.conditions import MISSING, evaluate_predicate
from maistro.graph.definitions import Graph
from maistro.graph.definitions import Node as GraphNode
from maistro.graph.execution_state import (
    GraphEdgeDecision,
    GraphExecutionState,
    thaw_json_value,
)
from maistro.graph.nodes.base import BaseNode, NodeContext, NodeResult
from maistro.runs.aggregation import derive_run_terminal_status, terminal_run_payload
from maistro.runs.lifecycle import (
    settle_open_node_run,
    transition_node_run,
    transition_path,
    transition_run,
)
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    GraphSnapshot,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.store import RunIntegrityError, RunStore

from .protocol import DurableRunStore
from .spine import mirror_lifecycle
from .types import DurableRunRecord

NodeResolver = Callable[[str, Graph], BaseNode[Any, Any]]

_DEPTH_INCREMENTING_KINDS = frozenset({"agent.synth_dag", "agent.spawn_harness"})
_PREDICATE_NAMESPACE_ALIASES = {
    "plan": "plan",
    "planner": "plan",
    "code": "code",
    "coder": "code",
    "review": "review",
    "reviewer": "review",
}


@dataclass(frozen=True)
class _FrontierItem:
    """Bind one active frontier node to its canonical NodeRun and execution inputs."""

    node_id: str
    spec: GraphNode
    node_run: NodeRun
    ctx: NodeContext
    result: NodeResult


def _replace_state(
    state: GraphExecutionState,
    **updates: object,
) -> GraphExecutionState:
    """Return a GraphExecutionState with only the requested fields replaced."""
    values = state.model_dump(mode="json")
    values.update({key: thaw_json_value(value) for key, value in updates.items()})
    return GraphExecutionState.model_validate(values)


def _replace_record(
    record: DurableRunRecord,
    **updates: object,
) -> DurableRunRecord:
    """Return a durable record with selected canonical state replaced."""
    values = record.model_dump(mode="json")
    values.update({key: thaw_json_value(value) for key, value in updates.items()})
    return DurableRunRecord.model_validate(values)


async def _checkpoint(
    record: DurableRunRecord,
    *,
    store: DurableRunStore,
    **updates: object,
) -> DurableRunRecord:
    """Persist the durable record and return the stored optimistic version."""
    return await store.update(_replace_record(record, version=record.version + 1, **updates))


def _require_admitted(run_id: str | None) -> str:
    """Refuse to bootstrap a Run the caller did not admit.

    `run_store` without a `run_id` used to mean "create one here". It cannot:
    the create and the first traversal checkpoint are two writes to two stores,
    and a crash between them leaves a canonical Run RUNNING that no durable
    record can resume and no sweep will notice. Admission is where Run identity
    is created, in one durable operation, and #251's consumer tick is what
    picks up the QUEUED Run it leaves behind.
    """
    if run_id is None:
        raise RunIntegrityError(
            "durable graph execution against the canonical RunStore requires an "
            "admitted run_id; admission owns Run identity"
        )
    return run_id


async def _adopt_admitted_run(
    graph: Graph,
    *,
    run_store: RunStore,
    run_id: str,
) -> Run:
    """Take the already-admitted Run as authority, and start it.

    The canonical path consumes a Run rather than creating one. Creating it
    here and checkpointing afterwards is a cross-store bootstrap with no
    recovery: a crash between the two leaves a canonical Run RUNNING with no
    traversal state to resume it from, and nothing to notice. Admission is the
    durable operation that owns Run identity, and a Run it left QUEUED is
    recoverable by the canonical consumer tick precisely because it is still
    QUEUED.

    A pinned `run_id` is an authority binding, not permission to reuse an
    identity. The Graph, workspace and Project on the admitted Run are checked
    against the ones supplied here, before any physical work: executing a
    different Graph under someone else's Run would attach its NodeRuns and
    Attempts to work nobody asked for, and the Run would then describe an
    execution that never happened.

    The Run is moved to RUNNING before the first frontier, because a node that
    runs while its canonical parent still says QUEUED is physical work no
    consumer of the spine can see is happening.
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
    if admitted.status is RunStatus.RUNNING:
        return admitted
    for step in transition_path(admitted.status, RunStatus.RUNNING):
        admitted = await run_store.transition_run(run_id, step)
    return admitted


async def _canonical_spine(
    record: DurableRunRecord,
    run_store: RunStore | None,
) -> RunStore | None:
    """Return the canonical store only when it actually holds this Run.

    Resolved once, at the top of a walk, rather than re-asked at each site.
    A record persisted before the convergence carries a Run the canonical
    store never saw, so minting its NodeRuns there would attach them to
    nothing; taking the pre-convergence path for it is what lets old records
    keep running instead of failing on resume.
    """
    if run_store is None:
        return None
    return run_store if await run_store.get_run(record.run_id) is not None else None


async def _adoptable_node_run(
    known: frozenset[str],
    node_id: str,
    *,
    record: DurableRunRecord,
    run_store: RunStore,
) -> NodeRun | None:
    """Find a canonical NodeRun this record lost before it could checkpoint.

    The canonical create and the traversal checkpoint are two writes to two
    stores. A crash between them leaves a NodeRun the spine holds and the
    aggregate does not, and minting a second one for the same visit would make
    the Run describe physical work twice. Adoption is what makes the retry
    idempotent: the identity already exists, so the record takes it rather than
    replacing it.
    """
    orphans = [
        node_run
        for node_run in await run_store.list_node_runs(record.run_id)
        if node_run.node_run_id not in known
        and node_run.node_id == node_id
        and node_run.status not in TERMINAL_RUN_STATUSES
    ]
    return orphans[-1] if orphans else None


async def _new_node_run(
    record: DurableRunRecord,
    node_id: str,
    *,
    ordinal: int,
    run_store: RunStore | None,
    known: frozenset[str] = frozenset(),
) -> NodeRun:
    """Obtain a frontier NodeRun, from the canonical store when there is one.

    The second of #44's three construction sites (ADR-082826-d9f5). The store
    allocates the ordinal from the NodeRuns it already holds for the Run, which
    is the same count the record keeps, so the aggregate's "consecutive in
    persistence order" invariant holds either way -- with a `run_store` every
    NodeRun of the Run is minted there, so the two counts cannot drift.
    """
    if run_store is None:
        node_run = NodeRun(run_id=record.run_id, node_id=node_id, ordinal=ordinal)
        node_run = transition_node_run(node_run, RunStatus.QUEUED)
        return transition_node_run(node_run, RunStatus.RUNNING)
    adopted = await _adoptable_node_run(known, node_id, record=record, run_store=run_store)
    canonical = (
        adopted
        if adopted is not None
        else await run_store.create_node_run(record.run_id, node_id=node_id)
    )
    for step in transition_path(canonical.status, RunStatus.RUNNING):
        canonical = await run_store.transition_node_run(canonical.node_run_id, step)
    return canonical


def _new_run(
    graph: Graph,
    *,
    run_id: str | None,
    actor_principal_id: str | None,
    parent_run_id: str | None = None,
    parent_node_run_id: str | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> Run:
    """Mint the canonical Run in memory for a graph launch.

    The pre-convergence path, kept for callers with no canonical store wired
    (`run_store=None`). `provenance` is merged over the executor's own marker
    rather than replacing it, so a caller records *why* the Run exists without
    erasing *how* it ran. `executor` stays first so a caller cannot
    accidentally reassign it -- a Run that claims a different executor than the
    one that walked it would make the field worse than absent.
    """
    values: dict[str, object] = {
        "workspace_id": graph.workspace_id,
        "project_id": graph.project_id,
        "graph": GraphSnapshot.from_graph(graph.model_copy(deep=True)),
        "actor_principal_id": actor_principal_id,
        "parent_run_id": parent_run_id,
        "parent_node_run_id": parent_node_run_id,
        "provenance": {**dict(provenance or {}), "executor": "durable_graph"},
    }
    if run_id is not None:
        values["run_id"] = run_id
    run = Run.model_validate(values)
    run = transition_run(run, RunStatus.QUEUED)
    return transition_run(run, RunStatus.RUNNING)


async def run_durable_graph(
    graph: Graph,
    *,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    inputs: dict[str, Any] | None = None,
    actor_principal_id: str | None = None,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    parent_node_run_id: str | None = None,
    provenance: Mapping[str, Any] | None = None,
    blackboard_metadata: Mapping[str, Any] | None = None,
    run_store: RunStore | None = None,
) -> DurableRunRecord:
    """Start and execute a durable graph from its canonical entry frontier.

    ``parent_run_id``/``parent_node_run_id`` make the launched Run a child of
    the Run (and NodeRun) that produced it — delegation and sub-graph work
    say "work is happening" as a child Run, not a second lifecycle.

    ``provenance`` records what admitted the work — `admission_source` and
    whatever identifies the thing that asked for it. Without it, a Run that a
    schedule fired is indistinguishable from one a person started, and the
    linkage survives only in an audit line beside the Run rather than on it
    (#145).
    """
    if run_store is not None:
        # The converged path (#44): the store owns the identity, and this
        # consumes it rather than creating a second one.
        run = await _adopt_admitted_run(
            graph,
            run_store=run_store,
            run_id=_require_admitted(run_id),
        )
    else:
        run = _new_run(
            graph,
            run_id=run_id,
            actor_principal_id=actor_principal_id,
            parent_run_id=parent_run_id,
            parent_node_run_id=parent_node_run_id,
            provenance=provenance,
        )
    state = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=(_entry_node(graph),),
        blackboard_snapshot={
            "task_objective": graph.name,
            "metadata": dict(blackboard_metadata or {}),
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
        run_store=run_store,
    )


async def resume_durable_graph(
    run_id: str,
    *,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    run_store: RunStore | None = None,
) -> DurableRunRecord:
    """Resume execution of a previously persisted durable graph run."""
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

    run = record.run
    if run.status is not RunStatus.RUNNING:
        run = transition_run(run, RunStatus.RUNNING)
    record = await _checkpoint(record, store=store, run=run, resume_at=None)
    return await _walk(
        record,
        store=store,
        node_resolver=node_resolver,
        run_store=run_store,
    )


async def _walk(
    record: DurableRunRecord,
    *,
    store: DurableRunStore,
    node_resolver: NodeResolver,
    max_steps: int = 256,
    run_store: RunStore | None = None,
) -> DurableRunRecord:
    """Execute one persisted frontier per step until pause or terminal state."""
    graph = record.run.graph.materialize()
    spine = await _canonical_spine(record, run_store)
    steps = 0

    while record.graph_state.active_node_ids and steps < max_steps:
        steps += 1
        frontier = record.graph_state.active_node_ids
        unknown = next(
            (node_id for node_id in frontier if _node_spec(graph, node_id) is None),
            None,
        )
        if unknown is not None:
            return await _mark_failed(
                record,
                error_code="UnknownNode",
                error_message=f"node_id={unknown!r} not present in Graph",
                store=store,
                run_store=spine,
            )

        record, node_runs = await _ensure_frontier_node_runs(
            record,
            frontier,
            store=store,
            run_store=spine,
        )
        items = await _execute_frontier(
            record,
            graph,
            frontier,
            node_runs,
            node_resolver=node_resolver,
        )
        record = await _fold_frontier(record, graph, items, store=store)
        await mirror_lifecycle(record, run_store=spine)
        if record.run.status is not RunStatus.RUNNING:
            return record

    record = await _finish_walk(record, store=store, max_steps=max_steps)
    await mirror_lifecycle(record, run_store=spine)
    return record


async def _execute_frontier(
    record: DurableRunRecord,
    graph: Graph,
    frontier: tuple[str, ...],
    node_runs: tuple[NodeRun, ...],
    *,
    node_resolver: NodeResolver,
) -> tuple[_FrontierItem, ...]:
    """Execute all prepared frontier nodes concurrently against one persisted snapshot."""
    prepared: list[
        tuple[
            str,
            GraphNode,
            NodeRun,
            NodeContext,
            BaseNode[Any, Any],
            dict[str, Any],
        ]
    ] = []
    for node_id, node_run in zip(frontier, node_runs, strict=True):
        spec = _node_spec(graph, node_id)
        assert spec is not None
        ctx = _build_ctx(record, node_id)
        node = node_resolver(node_id, graph)
        inputs = _resolve_inputs(graph, record, node_run, spec)
        prepared.append((node_id, spec, node_run, ctx, node, inputs))

    results = await asyncio.gather(
        *(node.run(inputs, ctx) for _, _, _, ctx, node, inputs in prepared)
    )
    return tuple(
        _FrontierItem(node_id, spec, node_run, ctx, result)
        for (node_id, spec, node_run, ctx, _, _), result in zip(
            prepared,
            results,
            strict=True,
        )
    )


def _classify_frontier_results(
    record: DurableRunRecord,
    items: tuple[_FrontierItem, ...],
) -> tuple[
    DurableRunRecord,
    tuple[_FrontierItem, ...],
    tuple[_FrontierItem, ...],
    tuple[_FrontierItem, ...],
]:
    """Terminalize frontier NodeRuns and partition their results by outcome."""
    node_runs = list(record.node_runs)
    completed: list[_FrontierItem] = []
    paused: list[_FrontierItem] = []
    failures: list[_FrontierItem] = []
    by_id = {item.node_run.node_run_id: item for item in items}

    for index, node_run in enumerate(node_runs):
        item = by_id.get(node_run.node_run_id)
        if item is None:
            continue
        if item.result.status == "paused":
            target = RunStatus.PAUSED if _is_human_pause(item.result) else RunStatus.WAITING
            node_runs[index] = transition_node_run(node_run, target)
            paused.append(item)
        elif item.result.success:
            node_runs[index] = transition_node_run(
                node_run,
                RunStatus.COMPLETED,
                result=_result_output(item.result),
            )
            completed.append(item)
        else:
            message = item.result.error_message or f"node {node_run.node_id} failed"
            error = f"{item.result.error_code or 'NodeFailure'}: {message}"[:512]
            node_runs[index] = transition_node_run(
                node_run,
                RunStatus.FAILED,
                error=error,
            )
            failures.append(item)

    updated = _replace_record(record, node_runs=tuple(node_runs))
    return updated, tuple(completed), tuple(paused), tuple(failures)


def _route_completed_items(
    record: DurableRunRecord,
    graph: Graph,
    completed: tuple[_FrontierItem, ...],
) -> tuple[tuple[str, ...], tuple[GraphEdgeDecision, ...]]:
    """Collect deterministic successor targets and immutable edge decisions."""
    targets: list[str] = []
    decisions: list[GraphEdgeDecision] = []
    for item in completed:
        item_targets, item_decisions = _next_nodes(
            graph,
            item.node_id,
            item.node_run.node_run_id,
            item.result,
            record,
        )
        targets.extend(item_targets)
        decisions.extend(item_decisions)
    return _dedupe(targets), tuple(decisions)


def _blackboard_halt_reason(record: DurableRunRecord) -> str | None:
    """Return the graph halt reason encoded in the current blackboard, if any."""
    metadata = record.graph_state.blackboard_snapshot.get("metadata", {})
    if not isinstance(metadata, Mapping) or not metadata.get("halt_requested"):
        return None
    return str(metadata.get("halt_reason") or "halt_requested")


def _deferred_frontier(record: DurableRunRecord) -> tuple[str, ...]:
    """Read the ordered deferred frontier from persisted graph state."""
    raw = record.graph_state.metadata.get("deferred_frontier", ())
    if not isinstance(raw, (tuple, list)):
        return ()
    return tuple(str(value) for value in raw)


def _deferred_fanins(record: DurableRunRecord) -> tuple[str, ...]:
    """Read deferred fan-in node identifiers from persisted graph state."""
    raw = record.graph_state.metadata.get("deferred_fanins", ())
    if not isinstance(raw, (tuple, list)):
        return ()
    return tuple(str(value) for value in raw)


def _latest_prior_node_run_ordinal(
    record: DurableRunRecord,
    node_id: str,
    *,
    before_ordinal: int | None = None,
) -> int:
    """Find the latest completed visit ordinal before the current frontier cycle."""
    return max(
        (
            node_run.ordinal
            for node_run in record.node_runs
            if node_run.node_id == node_id
            and (before_ordinal is None or node_run.ordinal < before_ordinal)
        ),
        default=0,
    )


def _selected_predecessor_decisions(
    record: DurableRunRecord,
    target_node_id: str,
    *,
    decisions: Iterable[GraphEdgeDecision] = (),
    before_ordinal: int | None = None,
) -> tuple[GraphEdgeDecision, ...]:
    """Select the latest routed predecessor decisions for one fan-in visit."""
    last_target_ordinal = _latest_prior_node_run_ordinal(
        record,
        target_node_id,
        before_ordinal=before_ordinal,
    )
    runs_by_id = {node_run.node_run_id: node_run for node_run in record.node_runs}
    latest_by_source: dict[str, tuple[int, GraphEdgeDecision]] = {}
    for decision in (*record.graph_state.edge_decisions, *tuple(decisions)):
        if not decision.selected or decision.target_node_id != target_node_id:
            continue
        source_run = runs_by_id.get(decision.source_node_run_id)
        if source_run is None or source_run.ordinal <= last_target_ordinal:
            continue
        current = latest_by_source.get(decision.source_node_id)
        if current is None or source_run.ordinal > current[0]:
            latest_by_source[decision.source_node_id] = (source_run.ordinal, decision)
    return tuple(
        decision for _, decision in sorted(latest_by_source.values(), key=lambda item: item[0])
    )


def _can_reach(graph: Graph, start_node_id: str, target_node_id: str) -> bool:
    """Return whether one graph node can structurally reach another node."""
    if start_node_id == target_node_id:
        return True
    seen = {start_node_id}
    frontier = [start_node_id]
    while frontier:
        current = frontier.pop()
        for edge in graph.edges:
            if edge.from_node != current or edge.to_node in seen:
                continue
            if edge.to_node == target_node_id:
                return True
            seen.add(edge.to_node)
            frontier.append(edge.to_node)
    return False


def _selected_predecessor_sources(
    record: DurableRunRecord,
    target_node_id: str,
    decisions: tuple[GraphEdgeDecision, ...],
) -> set[str]:
    """Return predecessor sources already selected for the target fan-in visit."""
    return {
        decision.source_node_id
        for decision in _selected_predecessor_decisions(
            record,
            target_node_id,
            decisions=decisions,
        )
    }


def _fanin_waits_for_live_branch(
    record: DurableRunRecord,
    graph: Graph,
    target: str,
    decisions: tuple[GraphEdgeDecision, ...],
    roots: tuple[str, ...],
) -> bool:
    """Return whether a fan-in must wait for a still-live predecessor branch."""
    incoming = _dedupe(edge.from_node for edge in graph.edges if edge.to_node == target)
    if len(incoming) <= 1:
        return False
    resolved = _selected_predecessor_sources(record, target, decisions)
    unresolved = tuple(node_id for node_id in incoming if node_id not in resolved)
    other_roots = tuple(node_id for node_id in roots if node_id != target)
    return any(
        any(_can_reach(graph, root, predecessor) for root in other_roots)
        for predecessor in unresolved
    )


def _partition_ready_targets(
    record: DurableRunRecord,
    graph: Graph,
    next_ids: tuple[str, ...],
    decisions: tuple[GraphEdgeDecision, ...],
    paused: tuple[_FrontierItem, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Partition successor targets into executable and deferred fan-in frontiers."""
    candidates = _dedupe((*_deferred_frontier(record), *_deferred_fanins(record), *next_ids))
    roots = _dedupe((*_deferred_frontier(record), *next_ids, *(item.node_id for item in paused)))
    ready: list[str] = []
    blocked: list[str] = []
    for target in candidates:
        target_list = (
            blocked
            if _fanin_waits_for_live_branch(record, graph, target, decisions, roots)
            else ready
        )
        target_list.append(target)
    return _dedupe(ready), _dedupe(blocked)


def _with_deferred_fanins(
    record: DurableRunRecord,
    node_ids: tuple[str, ...],
) -> DurableRunRecord:
    """Persist the deferred fan-in set without changing unrelated traversal state."""
    metadata = dict(record.graph_state.metadata)
    if node_ids:
        metadata["deferred_fanins"] = list(node_ids)
    else:
        metadata.pop("deferred_fanins", None)
    state = _replace_state(record.graph_state, metadata=metadata)
    return _replace_record(record, graph_state=state)


async def _checkpoint_paused_frontier(
    record: DurableRunRecord,
    paused: tuple[_FrontierItem, ...],
    next_ids: tuple[str, ...],
    decisions: tuple[GraphEdgeDecision, ...],
    *,
    store: DurableRunStore,
) -> DurableRunRecord:
    """Persist paused siblings together with successors deferred until resume."""
    metadata = dict(record.graph_state.metadata)
    pause_entries = {item.node_id: _pause_entry(item.result) for item in paused}
    existing_pauses = metadata.get("pauses", {})
    if isinstance(existing_pauses, Mapping):
        pause_entries = {**dict(existing_pauses), **pause_entries}
    metadata["pauses"] = pause_entries
    metadata["pause"] = pause_entries[paused[0].node_id]

    combined_next = _dedupe(next_ids)
    if combined_next:
        metadata["deferred_frontier"] = list(combined_next)
    else:
        metadata.pop("deferred_frontier", None)

    state = _replace_state(
        record.graph_state,
        active_node_ids=tuple(item.node_id for item in paused),
        edge_decisions=(*record.graph_state.edge_decisions, *decisions),
        metadata=metadata,
    )
    human = any(_is_human_pause(item.result) for item in paused)
    run = transition_run(
        record.run,
        RunStatus.PAUSED if human else RunStatus.WAITING,
    )
    resume_at = _earliest_resume(item.result.resume_at for item in paused)
    return await _checkpoint(
        record,
        store=store,
        run=run,
        graph_state=state,
        resume_at=resume_at,
    )


async def _checkpoint_next_frontier(
    record: DurableRunRecord,
    next_ids: tuple[str, ...],
    decisions: tuple[GraphEdgeDecision, ...],
    *,
    store: DurableRunStore,
) -> DurableRunRecord:
    """Persist the next executable frontier and advance the traversal cycle."""
    metadata = dict(record.graph_state.metadata)
    combined_next = _dedupe(next_ids)
    metadata.pop("pause", None)
    metadata.pop("pauses", None)
    metadata.pop("deferred_frontier", None)
    state = _replace_state(
        record.graph_state,
        active_node_ids=combined_next,
        cycle=record.graph_state.cycle + 1,
        edge_decisions=(*record.graph_state.edge_decisions, *decisions),
        metadata=metadata,
    )
    return await _checkpoint(
        record,
        store=store,
        graph_state=state,
        resume_at=None,
    )


async def _fold_frontier(
    record: DurableRunRecord,
    graph: Graph,
    items: tuple[_FrontierItem, ...],
    *,
    store: DurableRunStore,
) -> DurableRunRecord:
    """Fold concurrent results deterministically in active-frontier order."""
    record, completed, paused, failures = _classify_frontier_results(record, items)
    record = _merge_frontier_blackboards(record, items)
    for item in completed:
        record = _maybe_increment_synth_depth(record, item.spec, item.result)

    if failures:
        first = failures[0]
        return await _mark_failed(
            record,
            error_code=first.result.error_code or "NodeFailure",
            error_message=first.result.error_message or f"node {first.node_id} failed",
            store=store,
        )

    halt_reason = _blackboard_halt_reason(record)
    if halt_reason is not None:
        return await _mark_failed(
            record,
            error_code="HaltRequested",
            error_message=halt_reason,
            store=store,
        )

    next_ids, decisions = _route_completed_items(record, graph, completed)
    next_ids, blocked_fanins = _partition_ready_targets(
        record,
        graph,
        next_ids,
        decisions,
        paused,
    )
    record = _with_deferred_fanins(record, blocked_fanins)
    if paused:
        return await _checkpoint_paused_frontier(
            record,
            paused,
            next_ids,
            decisions,
            store=store,
        )
    return await _checkpoint_next_frontier(
        record,
        next_ids,
        decisions,
        store=store,
    )


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    """Deduplicate node identifiers while preserving deterministic encounter order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        node_id = str(value)
        if node_id not in seen:
            seen.add(node_id)
            result.append(node_id)
    return tuple(result)


def _is_human_pause(result: NodeResult) -> bool:
    """Return whether a node result represents a human-in-the-loop pause."""
    return str((result.metadata or {}).get("paused_reason") or "") in {
        "awaiting_human_answer",
        "awaiting_human_approval",
    }


def _pause_entry(result: NodeResult) -> dict[str, object]:
    """Build persisted pause metadata for one waiting frontier NodeRun."""
    return {
        "kind": "hitl" if _is_human_pause(result) else "wait",
        "metadata": dict(result.metadata or {}),
        "resume_at": result.resume_at.isoformat() if result.resume_at else None,
    }


def _earliest_resume(values: Iterable[datetime | None]) -> datetime | None:
    """Return the earliest resumable timestamp among paused frontier members."""
    present = [value for value in values if value is not None]
    return min(present) if present else None


async def _finish_walk(
    record: DurableRunRecord,
    *,
    store: DurableRunStore,
    max_steps: int,
) -> DurableRunRecord:
    """Terminalize graph traversal when no executable or deferred frontier remains."""
    if record.graph_state.active_node_ids:
        return await _mark_failed(
            record,
            error_code="StepBudgetExhausted",
            error_message=(
                f"run exceeded max_steps={max_steps} with frontier "
                f"{record.graph_state.active_node_ids!r} still pending; the graph may cycle"
            ),
            store=store,
        )
    return await _mark_completed(record, store=store)


def _entry_node(graph: Graph) -> str:
    """Resolve the canonical graph entry node identifier."""
    explicit = graph.metadata.get("entry_node") or graph.metadata.get("entry")
    if explicit:
        node_id = str(explicit)
        if _node_spec(graph, node_id) is None:
            raise ValueError(f"Graph entry node {node_id!r} does not exist")
        return node_id
    if not graph.nodes:
        raise ValueError("Graph has no nodes")
    incoming = {edge.to_node for edge in graph.edges}
    roots = [node.node_id for node in graph.nodes if node.node_id not in incoming]
    return roots[0] if roots else graph.nodes[0].node_id


def _node_spec(graph: Graph, node_id: str) -> GraphNode | None:
    """Resolve the immutable node specification for a graph node identifier."""
    return next((node for node in graph.nodes if node.node_id == node_id), None)


def _latest_nonterminal_node_run_index(
    record: DurableRunRecord,
    node_id: str,
) -> int | None:
    """Find the latest unfinished canonical NodeRun for a graph node."""
    for index in range(len(record.node_runs) - 1, -1, -1):
        node_run = record.node_runs[index]
        if node_run.node_id == node_id and node_run.status not in TERMINAL_RUN_STATUSES:
            return index
    return None


async def _ensure_frontier_node_runs(
    record: DurableRunRecord,
    frontier: tuple[str, ...],
    *,
    store: DurableRunStore,
    run_store: RunStore | None = None,
) -> tuple[DurableRunRecord, tuple[NodeRun, ...]]:
    """Resume or create one canonical running NodeRun per frontier member."""
    node_runs = list(record.node_runs)
    visit_counts = dict(record.graph_state.visit_counts)
    selected: list[NodeRun] = []
    changed = False

    for node_id in frontier:
        search_record = _replace_record(record, node_runs=tuple(node_runs))
        existing_index = _latest_nonterminal_node_run_index(search_record, node_id)
        if existing_index is not None:
            node_run = node_runs[existing_index]
            if node_run.status in {RunStatus.QUEUED, RunStatus.WAITING}:
                node_run = transition_node_run(node_run, RunStatus.RUNNING)
                node_runs[existing_index] = node_run
                changed = True
            elif node_run.status is RunStatus.PAUSED:
                raise ValueError("paused NodeRun must receive HITL input before execution")
            selected.append(node_run)
            continue

        node_run = await _new_node_run(
            record,
            node_id,
            ordinal=len(node_runs) + 1,
            run_store=run_store,
            known=frozenset(item.node_run_id for item in node_runs),
        )
        node_runs.append(node_run)
        selected.append(node_run)
        visit_counts[node_id] = visit_counts.get(node_id, 0) + 1
        changed = True

    if changed:
        state = _replace_state(record.graph_state, visit_counts=visit_counts)
        record = await _checkpoint(
            record,
            store=store,
            graph_state=state,
            node_runs=tuple(node_runs),
        )
    return record, tuple(selected)


def _value_at_path(value: object, path: str) -> object:
    """Resolve a dotted data path against nested mapping values."""
    for part in path.split("."):
        if isinstance(value, BaseModel):
            value = getattr(value, part, MISSING)
        elif isinstance(value, Mapping):
            value = value.get(part, MISSING)
        else:
            return MISSING
        if value is MISSING:
            return value
    return value


def _predicate_namespace(graph: Graph, node_id: str) -> str | None:
    """Build the predicate namespace exposed to conditional edge evaluation."""
    spec = _node_spec(graph, node_id)
    if spec is None:
        return None
    for value in (
        spec.metadata.get("role"),
        spec.metadata.get("agent_role"),
        spec.node_id,
        spec.node_type,
    ):
        token = str(value or "").lower().rsplit(".", 1)[-1]
        namespace = _PREDICATE_NAMESPACE_ALIASES.get(token)
        if namespace is not None:
            return namespace
    return None


def _completed_predicate_state(
    graph: Graph,
    record: DurableRunRecord | None,
) -> dict[str, object]:
    """Build predicate state from previously completed NodeRun outputs."""
    state: dict[str, object] = {}
    if record is None:
        return state
    for node_run in record.node_runs:
        if node_run.status is not RunStatus.COMPLETED or node_run.result is None:
            continue
        namespace = _predicate_namespace(graph, node_run.node_id)
        if namespace is not None:
            state[namespace] = node_run.result
    return state


def _merge_current_predicate_state(
    state: dict[str, object],
    graph: Graph,
    current_id: str,
    result: NodeResult,
) -> dict[str, object]:
    """Overlay current-frontier results onto prior predicate state."""
    output = result.output
    dumped = output.model_dump() if isinstance(output, BaseModel) else output
    if isinstance(dumped, Mapping):
        for slot in ("plan", "code", "review"):
            value = dumped.get(slot, MISSING)
            if value is not MISSING:
                state[slot] = value
    namespace = _predicate_namespace(graph, current_id)
    if namespace is not None and output is not None:
        state[namespace] = output
    return state


def _predicate_state(
    graph: Graph,
    current_id: str,
    result: NodeResult,
    record: DurableRunRecord | None,
) -> dict[str, object]:
    """Build the complete deterministic predicate state for edge routing."""
    return _merge_current_predicate_state(
        _completed_predicate_state(graph, record),
        graph,
        current_id,
        result,
    )


def _result_value(
    result: NodeResult,
    path: str,
    *,
    predicate_state: dict[str, object] | None = None,
) -> object:
    """Extract the value used by result-based edge conditions."""
    parts = path.split(".", 1)
    if len(parts) == 2 and predicate_state is not None:
        namespace, remainder = parts
        if namespace in predicate_state:
            return _value_at_path(predicate_state[namespace], remainder)
    return _value_at_path(result.output, path)


def _result_matches_condition(
    condition: str,
    result: NodeResult,
    *,
    predicate_state: dict[str, object] | None = None,
) -> bool:
    """Evaluate a result comparison condition against one node outcome."""
    return evaluate_predicate(
        condition,
        lambda path: _result_value(
            result,
            path,
            predicate_state=predicate_state,
        ),
    )


def _edge_parallel(edge: Any) -> bool:
    """Return whether an edge participates in parallel fan-out routing."""
    return bool(edge.metadata.get("parallel", False))


def _next_nodes(
    graph: Graph,
    current_id: str,
    source_node_run_id: str,
    result: NodeResult,
    record: DurableRunRecord | None = None,
) -> tuple[tuple[str, ...], tuple[GraphEdgeDecision, ...]]:
    """Select first eligible sequential edge plus every eligible parallel edge."""
    predicate_state = _predicate_state(graph, current_id, result, record)
    decisions: list[GraphEdgeDecision] = []
    targets: list[str] = []
    sequential_selected = False
    cycle = record.graph_state.cycle if record is not None else 0

    for edge in graph.edges:
        if edge.from_node != current_id:
            continue
        eligible = edge.condition is None or _result_matches_condition(
            edge.condition,
            result,
            predicate_state=predicate_state,
        )
        parallel = _edge_parallel(edge)
        selected = eligible and (parallel or not sequential_selected)
        if selected:
            targets.append(edge.to_node)
            if not parallel:
                sequential_selected = True
        decisions.append(
            GraphEdgeDecision(
                edge_id=edge.edge_id,
                source_node_id=current_id,
                source_node_run_id=source_node_run_id,
                target_node_id=edge.to_node,
                selected=selected,
                cycle=cycle,
                condition=edge.condition,
            )
        )
    return _dedupe(targets), tuple(decisions)


def _next_node(
    graph: Graph,
    current_id: str,
    source_node_run_id: str,
    result: NodeResult,
    record: DurableRunRecord | None = None,
) -> tuple[str | None, tuple[GraphEdgeDecision, ...]]:
    """Return the first selected sequential successor for compatibility callers."""
    targets, decisions = _next_nodes(
        graph,
        current_id,
        source_node_run_id,
        result,
        record,
    )
    return (targets[0] if targets else None), decisions


def _initial_inputs(record: DurableRunRecord) -> dict[str, Any]:
    """Return the immutable launch inputs recorded for the graph run."""
    value = record.graph_state.metadata.get("initial_inputs", {})
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve_inputs(
    graph: Graph,
    record: DurableRunRecord,
    current: NodeRun,
    spec: GraphNode,
) -> dict[str, Any]:
    """Merge selected immediate-predecessor outputs for deterministic fan-in."""
    static_inputs = {**spec.parameters, **spec.inputs}
    if record.graph_state.cycle == 0:
        return {**static_inputs, **_initial_inputs(record)}

    source_run_ids = [
        decision.source_node_run_id
        for decision in _selected_predecessor_decisions(
            record,
            current.node_id,
            before_ordinal=current.ordinal,
        )
    ]
    results_by_id = {node_run.node_run_id: node_run.result for node_run in record.node_runs}
    upstream: dict[str, Any] = {}
    for source_run_id in source_run_ids:
        output = results_by_id.get(source_run_id)
        if isinstance(output, Mapping):
            upstream.update(dict(output))
    if source_run_ids:
        return {**static_inputs, **upstream}
    return {**static_inputs, **_initial_inputs(record)}


def _merge_changed_mapping(
    base: Mapping[str, Any],
    current: Mapping[str, Any],
    merged: dict[str, Any],
) -> None:
    """Merge only mapping values changed by a completed frontier member."""
    for key in set(base) | set(current):
        if key not in current:
            if key in base:
                merged.pop(key, None)
        elif key not in base or current[key] != base[key]:
            merged[key] = current[key]


def _merge_frontier_blackboards(
    record: DurableRunRecord,
    items: tuple[_FrontierItem, ...],
) -> DurableRunRecord:
    """Merge sibling blackboard deltas in deterministic frontier order."""
    base_snapshot = dict(record.graph_state.blackboard_snapshot)
    base_metadata = dict(base_snapshot.get("metadata") or {})
    base_annotations = dict(base_snapshot.get("node_annotations") or {})
    metadata = dict(base_metadata)
    annotations = dict(base_annotations)

    for item in items:
        blackboard = item.ctx.blackboard
        if blackboard is None:
            continue
        current_metadata = dict(getattr(blackboard, "metadata", {}) or {})
        current_annotations = dict(getattr(blackboard, "node_annotations", {}) or {})
        _merge_changed_mapping(base_metadata, current_metadata, metadata)
        _merge_changed_mapping(base_annotations, current_annotations, annotations)

    snapshot = dict(base_snapshot)
    snapshot["metadata"] = metadata
    snapshot["node_annotations"] = annotations
    return _replace_record(
        record,
        graph_state=_replace_state(
            record.graph_state,
            blackboard_snapshot=snapshot,
        ),
    )


def _actually_spawned(kind: str, result: NodeResult) -> bool:
    """Return whether a node result represents a successful synthetic spawn."""
    if kind == "agent.synth_dag":
        output = result.output
        return bool(getattr(output, "success", True)) or bool(getattr(output, "dispatched", False))
    return True


def _maybe_increment_synth_depth(
    record: DurableRunRecord,
    spec: GraphNode,
    result: NodeResult,
) -> DurableRunRecord:
    """Increment synthesis depth only when the node actually spawned work."""
    if spec.node_type not in _DEPTH_INCREMENTING_KINDS or not _actually_spawned(
        spec.node_type,
        result,
    ):
        return record
    snapshot = dict(record.graph_state.blackboard_snapshot)
    metadata = dict(snapshot.get("metadata") or {})
    metadata["synth_depth"] = int(metadata.get("synth_depth", 0)) + 1
    snapshot["metadata"] = metadata
    state = _replace_state(record.graph_state, blackboard_snapshot=snapshot)
    return _replace_record(record, graph_state=state)


def _build_ctx(record: DurableRunRecord, node_id: str) -> NodeContext:
    """Build the runtime execution context for one canonical NodeRun."""
    from maistro.graph.types import GraphBlackboard

    snapshot = record.graph_state.blackboard_snapshot
    try:
        blackboard = GraphBlackboard(
            task_objective=str(snapshot.get("task_objective") or ""),
            workspace=str(snapshot.get("workspace") or ""),
            metadata=dict(snapshot.get("metadata") or {}),
            node_annotations=dict(snapshot.get("node_annotations") or {}),
        )
    except Exception:
        blackboard = None
    try:
        synth_depth = dict(snapshot.get("metadata") or {}).get("synth_depth", 0)
    except (TypeError, ValueError):
        synth_depth = 0
    return NodeContext(
        run_id=record.run_id,
        dag_id=record.run.graph.graph_id,
        node_id=node_id,
        user_id=record.run.actor_principal_id,
        workspace_id=record.run.workspace_id,
        project_id=record.run.project_id,
        blackboard=blackboard,
        metadata={
            "hitl_answers": dict(record.hitl_answers),
            "synth_depth": synth_depth,
        },
    )


def _replace_node_run(
    record: DurableRunRecord,
    updated: NodeRun,
) -> DurableRunRecord:
    """Return a NodeRun with selected lifecycle or result fields replaced."""
    node_runs = list(record.node_runs)
    for index, node_run in enumerate(node_runs):
        if node_run.node_run_id == updated.node_run_id:
            node_runs[index] = updated
            return _replace_record(record, node_runs=tuple(node_runs))
    raise KeyError(updated.node_run_id)


def _result_output(result: NodeResult) -> object | None:
    """Normalize a node execution result into its persisted output mapping."""
    output = result.output
    if isinstance(output, BaseModel):
        return output.model_dump(mode="json")
    return output


def _clear_pause_metadata(state: GraphExecutionState) -> GraphExecutionState:
    """Remove pause metadata after the corresponding frontier has resumed."""
    metadata = dict(state.metadata)
    metadata.pop("pause", None)
    metadata.pop("pauses", None)
    return _replace_state(state, metadata=metadata)


async def _mark_completed(
    record: DurableRunRecord,
    *,
    store: DurableRunStore,
) -> DurableRunRecord:
    """Terminalize a successful NodeRun and persist its normalized output."""
    work_owed = bool(
        record.graph_state.active_node_ids or _deferred_frontier(record) or _deferred_fanins(record)
    )
    target = derive_run_terminal_status(record.node_runs, work_owed=work_owed)
    if target is None:
        raise ValueError("cannot terminalize a Graph Run while logical frontier work is owed")
    result, error = terminal_run_payload(record.node_runs, target)
    run = transition_run(record.run, target, result=result, error=error)
    state = _replace_state(record.graph_state, active_node_ids=())
    return await _checkpoint(
        record,
        store=store,
        run=run,
        graph_state=state,
        resume_at=None,
    )


def _running_run(run: Run) -> Run:
    """Return the parent Run in its canonical running lifecycle state."""
    if run.status is RunStatus.RUNNING:
        return run
    if run.status is RunStatus.PAUSED:
        run = transition_run(run, RunStatus.QUEUED)
    if run.status is RunStatus.CREATED:
        run = transition_run(run, RunStatus.QUEUED)
    if run.status in {RunStatus.QUEUED, RunStatus.WAITING}:
        return transition_run(run, RunStatus.RUNNING)
    return run


def _settle_open_node_runs(
    record: DurableRunRecord,
    run_target: RunStatus,
) -> DurableRunRecord:
    """Settle every open NodeRun because the parent Run is terminalizing.

    The *rule* — what an open node settles to, and what its error says — is
    `settle_open_node_run`'s, shared with the canonical stores
    (ADR-082426-a47f). Only the walk is local, because a durable Graph run
    holds its NodeRuns in one checkpointed record rather than as rows.

    ``run_target`` is passed rather than assumed. This used to write "cancelled
    because the durable run failed" on both paths, so a *cancelled* Run's nodes
    claimed it had failed.
    """
    node_runs = list(record.node_runs)
    changed = False
    for index, node_run in enumerate(node_runs):
        if node_run.status in TERMINAL_RUN_STATUSES:
            continue
        node_runs[index] = settle_open_node_run(node_run, run_target)
        changed = True
    if not changed:
        return record
    return _replace_record(record, node_runs=tuple(node_runs))


async def _mark_failed(
    record: DurableRunRecord,
    *,
    error_code: str,
    error_message: str,
    store: DurableRunStore,
    run_store: RunStore | None = None,
) -> DurableRunRecord:
    """Terminalize the parent Run and reconcile unfinished NodeRuns after failure.

    Mirrors here rather than at the call site because this is a terminal exit
    the walk does not come back from: a Run left RUNNING on the spine because
    its graph failed is work nothing will ever recover, since recovery only
    looks at what the store says is still open.
    """
    record = _settle_open_node_runs(record, RunStatus.FAILED)
    run = _running_run(record.run)
    error = f"{error_code}: {error_message}"[:512]
    if run.status is not RunStatus.RUNNING:
        raise ValueError(f"cannot fail run in status {run.status!r}")
    run = transition_run(run, RunStatus.FAILED, error=error)
    state = _replace_state(record.graph_state, active_node_ids=())
    failed = await _checkpoint(
        record,
        store=store,
        run=run,
        graph_state=state,
    )
    await mirror_lifecycle(failed, run_store=run_store)
    return failed


__all__ = ["NodeResolver", "resume_durable_graph", "run_durable_graph"]
