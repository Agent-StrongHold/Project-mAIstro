"""Atomic logical acceptance and authoritative Graph traversal advancement.

Physical Attempts are already durable before this module runs. This fold turns
those immutable physical results into accepted logical NodeRun outcomes and, for
an advancing frontier, persists the resulting GraphExecutionState and
TraversalCommit in the same optimistic durable checkpoint.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from maistro.graph.definitions import Graph
from maistro.graph.execution_state import GraphEdgeDecision, GraphExecutionState
from maistro.graph.traversal_commit import (
    TraversalCheckpoint,
    TraversalCommit,
    graph_state_hash,
)
from maistro.graph.verification.expectations import PlanExpectationQueue
from maistro.graph.verification.taxonomy import classify_result_state
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.model import (
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    NodeRun,
    RunStatus,
)

from . import executor as traversal
from .failure import sanitize_failure_message
from .protocol import DurableRunStore
from .types import DurableRunRecord


def _plan_mismatch_error(
    graph: Graph,
    completed: tuple[traversal._FrontierItem, ...],
) -> str | None:
    """Supervise completed nodes against the plan queue's predicted post-states.

    A plan is a claim about the future (epic M4-I). When a completed node's
    actual post-state contradicts its declared
    ``policies[\"expect_post_state\"]`` prediction, the Run halts here with
    ``PlanPostStateMismatch`` instead of routing the contradicted state
    onward — the same visible-stop contract the blackboard halt uses, and
    deliberately a failure rather than a pause: nothing external is owed an
    answer, and resuming without new work would only re-read the same world.
    """
    if not completed:
        return None
    queue = PlanExpectationQueue.from_graph(graph)
    if not queue.expectations:
        return None
    for item in completed:
        verdict = queue.supervise(
            item.node_id,
            output=traversal._result_output(item.result),
            result_state=classify_result_state(item.result),
        )
        if verdict is not None and not verdict.matched:
            suffix = (
                f" [{item.spec.policies['expect_post_state'].get('description')}]"
                if isinstance(item.spec.policies.get("expect_post_state"), Mapping)
                and item.spec.policies["expect_post_state"].get("description")
                else ""
            )
            # The halt names what the plan still awaited: the durable
            # explanation covers not just the contradicted prediction but the
            # work the plan predicted had not happened yet.
            pending = queue.pending_node_ids
            pending_note = f" (plan still awaiting: {', '.join(pending)})" if pending else ""
            return f"{verdict.describe()}{suffix}{pending_note}"
    return None


def _visit_quality(item: traversal._FrontierItem) -> float | None:
    """The visit's self-reported quality, or ``None`` when it reports none."""
    from maistro.graph.verification.escalation import QUALITY_METADATA_KEY

    raw_quality = (item.result.metadata or {}).get(QUALITY_METADATA_KEY)
    if isinstance(raw_quality, (int, float)) and not isinstance(raw_quality, bool):
        return float(raw_quality)
    return None


def _escalate_one_visit(
    record: DurableRunRecord,
    item: traversal._FrontierItem,
    escalations: dict[str, Any],
    declared: tuple[Any, Any],
    quality: float,
) -> bool:
    """Record one visit's ladder decision; ``True`` when it re-queues at a rung.

    The re-queued visit is a fresh NodeRun/Attempt whose context names the
    chosen rung; a decision not to escalate (floor met, ladder exhausted, or
    no visit left) clears any prior rung state so the acceptance is final.
    """
    from maistro.graph.verification.escalation import decide_escalation

    ladder, gate = declared
    current = escalations.get(item.node_id, {}).get("model")
    decision = decide_escalation(ladder, current, quality, gate)
    if not (
        decision.escalate
        and decision.to_model is not None
        and traversal._may_revisit_after(record.graph_state, item)
    ):
        return False
    escalations[item.node_id] = {
        "model": decision.to_model,
        "rung": ladder.index_of(decision.to_model),
        "from_model": decision.from_model,
        "quality": decision.quality,
    }
    return True


def _escalate_quality_shortfalls(
    record: DurableRunRecord,
    completed: tuple[traversal._FrontierItem, ...],
) -> tuple[DurableRunRecord, tuple[traversal._FrontierItem, ...], tuple[str, ...]]:
    """Withhold quality-short visits and re-queue them at the next ladder rung.

    Cheap-first escalation (epic M4-I): a completed visit whose self-reported
    ``quality`` metadata misses the node's declared floor is *not accepted as
    final* while a stronger rung and visit budget remain. Its edges do not
    route this cycle; it re-enters the frontier as a fresh NodeRun/Attempt —
    never a rewritten one — whose ``NodeContext.metadata["escalated_model"]``
    names the rung to run. Exhausted budgets and exhausted ladders accept the
    shortfall as final: supervision may not become an unbounded loop, and the
    accepted visit's own metadata still records the shortfall for anyone
    reading the evidence.
    """
    from maistro.graph.verification.escalation import (
        ESCALATION_STATE_METADATA_KEY,
        escalation_from_policy,
    )

    if not completed:
        return record, completed, ()
    escalations: dict[str, Any] = {
        str(node_id): dict(entry)
        for node_id, entry in (
            record.graph_state.metadata.get(ESCALATION_STATE_METADATA_KEY) or {}
        ).items()
        if isinstance(entry, Mapping)
    }
    advanced: list[traversal._FrontierItem] = []
    requeued: list[str] = []
    changed = False
    for item in completed:
        declared = escalation_from_policy(item.spec.policies)
        quality = _visit_quality(item)
        if declared is None or quality is None:
            changed |= escalations.pop(item.node_id, None) is not None
            advanced.append(item)
            continue
        if _escalate_one_visit(record, item, escalations, declared, quality):
            requeued.append(item.node_id)
            changed = True
        else:
            changed |= escalations.pop(item.node_id, None) is not None
            advanced.append(item)
    if not changed:
        return record, completed, ()
    return _commit_escalation_state(record, escalations), tuple(advanced), tuple(requeued)


def _commit_escalation_state(
    record: DurableRunRecord, escalations: dict[str, Any]
) -> DurableRunRecord:
    """Write the ladder decisions into graph state; an empty map clears them."""
    from maistro.graph.verification.escalation import ESCALATION_STATE_METADATA_KEY

    metadata = dict(record.graph_state.metadata)
    if escalations:
        metadata[ESCALATION_STATE_METADATA_KEY] = escalations
    else:
        metadata.pop(ESCALATION_STATE_METADATA_KEY, None)
    return traversal._replace_record(
        record,
        graph_state=traversal._replace_state(record.graph_state, metadata=metadata),
    )


def _completed_attempt_result(record: DurableRunRecord, node_run_id: str) -> AttemptResult:
    attempt = next(
        (
            item
            for item in reversed(record.attempts)
            if item.node_run_id == node_run_id and item.status is AttemptStatus.COMPLETED
        ),
        None,
    )
    if attempt is None:
        raise ValueError(f"NodeRun {node_run_id!r} has no persisted completed Attempt")
    return AttemptResult.from_attempt(attempt)


def _accept_exhausted_failure(record: DurableRunRecord, item: traversal._FrontierItem) -> bool:
    """Return whether node policy accepts an exhausted failure as domain output.

    Retry authority stays in the canonical traversal rule from #573. This policy
    applies only once that rule says no visit remains. The physical AttemptResult
    stays failed evidence; only the accepted logical NodeRun disposition becomes
    COMPLETED so a domain such as MasterOrchestrator can project FAILED without
    aborting unrelated Graph work.
    """
    return item.spec.policies.get(
        "continue_on_failure"
    ) is True and not traversal._may_revisit_after(record.graph_state, item)


def _logical_outcome(
    record: DurableRunRecord,
    item: traversal._FrontierItem,
) -> AcceptedNodeOutcome:
    physical = _completed_attempt_result(record, item.node_run.node_run_id)
    if item.result.status == "paused":
        logical_status = (
            RunStatus.PAUSED if traversal._is_human_pause(item.result) else RunStatus.WAITING
        )
        result = None
        error = None
    elif item.result.success or _accept_exhausted_failure(record, item):
        logical_status = RunStatus.COMPLETED
        result = traversal._result_output(item.result)
        error = None
    else:
        logical_status = RunStatus.FAILED
        result = None
        message = sanitize_failure_message(
            item.result.error_message or f"node {item.node_id} failed"
        )
        error = f"{item.result.error_code or 'NodeFailure'}: {message}"[:512]
    return AcceptedNodeOutcome(
        node_run_id=item.node_run.node_run_id,
        attempt_result=physical,
        logical_status=logical_status,
        result=result,
        error=error,
    )


def _accept_frontier(
    record: DurableRunRecord,
    items: tuple[traversal._FrontierItem, ...],
) -> tuple[
    DurableRunRecord,
    tuple[traversal._FrontierItem, ...],
    tuple[traversal._FrontierItem, ...],
    tuple[traversal._FrontierItem, ...],
]:
    """Project completed physical evidence into logical outcomes in memory only."""
    node_runs = list(record.node_runs)
    by_id = {node_run.node_run_id: index for index, node_run in enumerate(node_runs)}
    completed: list[traversal._FrontierItem] = []
    paused: list[traversal._FrontierItem] = []
    failures: list[traversal._FrontierItem] = []

    for item in items:
        outcome = _logical_outcome(record, item)
        index = by_id[item.node_run.node_run_id]
        node_run = node_runs[index]
        node_runs[index] = transition_node_run(
            node_run,
            outcome.logical_status,
            result=outcome.result,
            error=outcome.error,
            accepted_outcome=outcome,
        )
        if outcome.logical_status in {RunStatus.PAUSED, RunStatus.WAITING}:
            paused.append(item)
        elif outcome.logical_status is RunStatus.COMPLETED:
            completed.append(item)
        else:
            failures.append(item)

    return (
        traversal._replace_record(record, node_runs=tuple(node_runs)),
        tuple(completed),
        tuple(paused),
        tuple(failures),
    )


def _accepted_outcomes(
    record: DurableRunRecord,
    completed: tuple[traversal._FrontierItem, ...],
) -> tuple[AcceptedNodeOutcome, ...]:
    runs = {node_run.node_run_id: node_run for node_run in record.node_runs}
    outcomes: list[AcceptedNodeOutcome] = []
    for item in completed:
        node_run: NodeRun = runs[item.node_run.node_run_id]
        if node_run.accepted_outcome is None:
            raise ValueError("advancing source NodeRun is missing accepted outcome")
        outcomes.append(node_run.accepted_outcome)
    return tuple(outcomes)


def _checkpoint_bridge(
    record: DurableRunRecord,
    prior_state: GraphExecutionState,
    completed: tuple[traversal._FrontierItem, ...],
) -> tuple[TraversalCheckpoint | None, tuple[TraversalCheckpoint, ...]]:
    """Capture an intervening non-advancing state before the next commit.

    A pause, wait, HITL answer, or recovery checkpoint may legitimately mutate
    GraphExecutionState without advancing traversal. The next TraversalCommit
    must hash the exact state it advances from, so materialize that state as a
    TraversalCheckpoint instead of weakening adjacent commit hash validation.
    """
    prior = record.latest_traversal_commit
    if prior is None or prior.resulting_state_hash == graph_state_hash(prior_state):
        return None, record.traversal_checkpoints

    prior_hash = graph_state_hash(prior_state)
    referenced = {
        commit.checkpoint_id for commit in record.traversal_commits if commit.checkpoint_id
    }
    latest = record.latest_traversal_checkpoint
    if (
        latest is not None
        and latest.traversal_checkpoint_id not in referenced
        and latest.state_hash == prior_hash
    ):
        return latest, record.traversal_checkpoints

    checkpoint = TraversalCheckpoint.from_state(
        graph_snapshot_hash=record.run.graph.content_hash,
        state=prior_state,
        ordered_source_node_run_ids=tuple(item.node_run.node_run_id for item in completed),
        checkpoint_sequence=len(record.traversal_checkpoints) + 1,
    )
    return checkpoint, (*record.traversal_checkpoints, checkpoint)


async def _checkpoint_advancement(
    record: DurableRunRecord,
    prior_state: GraphExecutionState,
    completed: tuple[traversal._FrontierItem, ...],
    next_ids: tuple[str, ...],
    decisions: tuple[GraphEdgeDecision, ...],
    *,
    store: DurableRunStore,
) -> DurableRunRecord:
    """Persist accepted NodeRuns, traversal state, checkpoint bridge, and commit atomically."""
    metadata = dict(record.graph_state.metadata)
    combined_next = traversal._dedupe(next_ids)
    metadata.pop("pause", None)
    metadata.pop("pauses", None)
    metadata.pop("deferred_frontier", None)
    state = traversal._replace_state(
        record.graph_state,
        active_node_ids=combined_next,
        cycle=record.graph_state.cycle + 1,
        edge_decisions=(*record.graph_state.edge_decisions, *decisions),
        metadata=metadata,
    )
    prior = record.latest_traversal_commit
    checkpoint, checkpoints = _checkpoint_bridge(record, prior_state, completed)
    commit = TraversalCommit.from_transition(
        graph_snapshot_hash=record.run.graph.content_hash,
        prior_state=prior_state,
        resulting_state=state,
        ordered_source_node_run_ids=tuple(item.node_run.node_run_id for item in completed),
        accepted_outcomes=_accepted_outcomes(record, completed),
        edge_decisions=decisions,
        commit_sequence=len(record.traversal_commits) + 1,
        prior_commit_id=prior.traversal_commit_id if prior is not None else None,
        checkpoint_id=checkpoint.traversal_checkpoint_id if checkpoint is not None else None,
    )
    return await traversal._checkpoint(
        record,
        store=store,
        graph_state=state,
        traversal_checkpoints=checkpoints,
        traversal_commits=(*record.traversal_commits, commit),
        resume_at=None,
    )


async def _fold_failures(
    record: DurableRunRecord,
    graph: Graph,
    completed: tuple[traversal._FrontierItem, ...],
    failures: tuple[traversal._FrontierItem, ...],
    *,
    prior_state: GraphExecutionState,
    store: DurableRunStore,
) -> DurableRunRecord:
    """Retry failed visits without discarding completed sibling advancement."""
    exhausted = traversal.first_exhausted_failure(prior_state, failures)
    if exhausted is not None:
        return await traversal._mark_failed(
            record,
            error_code=exhausted.result.error_code or "NodeFailure",
            error_message=exhausted.result.error_message or f"node {exhausted.node_id} failed",
            store=store,
        )

    next_ids, decisions = traversal._route_completed_items(record, graph, completed)
    retry_ids = tuple(item.node_id for item in failures)
    candidates = traversal._dedupe((*retry_ids, *next_ids))
    ready, blocked_fanins = traversal._partition_ready_targets(
        record,
        graph,
        candidates,
        decisions,
        failures,
    )
    record = traversal._with_deferred_fanins(record, blocked_fanins)
    return await _checkpoint_advancement(
        record,
        prior_state,
        completed,
        ready,
        decisions,
        store=store,
    )


async def fold_authoritative_frontier(
    record: DurableRunRecord,
    graph: Graph,
    items: tuple[traversal._FrontierItem, ...],
    *,
    store: DurableRunStore,
) -> DurableRunRecord:
    """Fold physical frontier results through one authoritative logical boundary."""
    prior_state = record.graph_state
    record, completed, paused, failures = _accept_frontier(record, items)
    record = traversal._merge_frontier_blackboards(record, items)
    # A failed synth node whose dispatched child failed still spent a level
    # (#1193): its retry must start from the deeper depth.
    dispatched_failures = tuple(item for item in failures if item.result.metadata.get("dispatched"))
    for item in (*completed, *dispatched_failures):
        record = traversal._maybe_increment_synth_depth(record, item.spec, item.result)

    if failures:
        return await _fold_failures(
            record,
            graph,
            completed,
            failures,
            prior_state=prior_state,
            store=store,
        )

    halt_reason = traversal._blackboard_halt_reason(record)
    if halt_reason is not None:
        return await traversal._mark_failed(
            record,
            error_code="HaltRequested",
            error_message=halt_reason,
            store=store,
        )

    mismatch = _plan_mismatch_error(graph, completed)
    if mismatch is not None:
        return await traversal._mark_failed(
            record,
            error_code="PlanPostStateMismatch",
            error_message=mismatch,
            store=store,
        )

    record, completed, escalated_ids = _escalate_quality_shortfalls(record, completed)

    next_ids, decisions = traversal._route_completed_items(record, graph, completed)
    next_ids = traversal._dedupe((*next_ids, *escalated_ids))
    next_ids, blocked_fanins = traversal._partition_ready_targets(
        record,
        graph,
        next_ids,
        decisions,
        paused,
    )
    record = traversal._with_deferred_fanins(record, blocked_fanins)
    if paused:
        return await traversal._checkpoint_paused_frontier(
            record,
            paused,
            next_ids,
            decisions,
            store=store,
        )
    return await _checkpoint_advancement(
        record,
        prior_state,
        completed,
        next_ids,
        decisions,
        store=store,
    )


__all__ = ["fold_authoritative_frontier"]
