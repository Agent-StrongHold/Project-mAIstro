"""Atomic logical acceptance and authoritative Graph traversal advancement.

Physical Attempts are already durable before this module runs. This fold turns
those immutable physical results into accepted logical NodeRun outcomes and, for
an advancing frontier, persists the resulting GraphExecutionState and
TraversalCommit in the same optimistic durable checkpoint.
"""

from __future__ import annotations

from maistro.graph.definitions import Graph
from maistro.graph.execution_state import GraphEdgeDecision, GraphExecutionState
from maistro.graph.traversal_commit import (
    TraversalCheckpoint,
    TraversalCommit,
    graph_state_hash,
)
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.model import (
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    NodeRun,
    RunStatus,
)

from . import executor as traversal
from .protocol import DurableRunStore
from .types import DurableRunRecord


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
    elif item.result.success:
        logical_status = RunStatus.COMPLETED
        result = traversal._result_output(item.result)
        error = None
    else:
        logical_status = RunStatus.FAILED
        result = None
        message = item.result.error_message or f"node {item.node_id} failed"
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
    failures: tuple[traversal._FrontierItem, ...],
    *,
    prior_state: GraphExecutionState,
    store: DurableRunStore,
) -> DurableRunRecord:
    """Fail the Run, or send back the nodes whose own policy says try again.

    A failure with a visit left is not the Run's failure yet (#548). The retry
    is the node's next visit -- a new NodeRun with its own Attempt -- because
    the Attempt firewall rightly refuses to redispatch a completed Attempt:
    completion means the physical work ran, side effects and all.

    `prior_state` rather than `record.graph_state` because the accept above
    already counted this visit; asking the pre-fold state keeps the budget
    meaning "tries" rather than "tries minus the one being decided".

    Which failures are out of budget is `traversal.first_exhausted_failure`,
    the same rule the other fold asks -- not a second copy of it.
    """
    exhausted = traversal.first_exhausted_failure(prior_state, failures)
    if exhausted is not None:
        return await traversal._mark_failed(
            record,
            error_code=exhausted.result.error_code or "NodeFailure",
            error_message=exhausted.result.error_message or f"node {exhausted.node_id} failed",
            store=store,
        )
    return await _checkpoint_advancement(
        record,
        prior_state,
        (),
        tuple(item.node_id for item in failures),
        (),
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
    for item in completed:
        record = traversal._maybe_increment_synth_depth(record, item.spec, item.result)

    if failures:
        return await _fold_failures(
            record,
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

    next_ids, decisions = traversal._route_completed_items(record, graph, completed)
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
