from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.graph import (
    Edge,
    Graph,
    GraphEdgeDecision,
    GraphExecutionState,
    Node,
    TraversalCheckpoint,
    TraversalCommit,
)
from maistro.graph.durable_runs import DurableRunRecord
from maistro.runs import (
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    GraphSnapshot,
    NodeRun,
    Run,
    RunStatus,
)


def _outcome(node_run_id: str, attempt_id: str, result: object) -> AcceptedNodeOutcome:
    return AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult(
            attempt_id=attempt_id,
            node_run_id=node_run_id,
            ordinal=1,
            status=AttemptStatus.COMPLETED,
            result=result,
            finished_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
        ),
        logical_status=RunStatus.COMPLETED,
        result=result,
    )


def _history() -> tuple[
    Run,
    tuple[NodeRun, NodeRun],
    GraphExecutionState,
    TraversalCheckpoint,
    tuple[TraversalCommit, TraversalCommit],
]:
    graph = Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Checkpoint bridge",
        nodes=[
            Node(node_id="a", node_type="agent"),
            Node(node_id="b", node_type="agent"),
        ],
        edges=[Edge(edge_id="a-b", from_node="a", to_node="b")],
    )
    run = Run(
        run_id="run-1",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.RUNNING,
    )

    first_outcome = _outcome("node-run-a", "attempt-a", {"value": "a"})
    first_run = NodeRun(
        node_run_id="node-run-a",
        run_id=run.run_id,
        node_id="a",
        ordinal=1,
        status=RunStatus.COMPLETED,
        finished_at=first_outcome.attempt_result.finished_at,
        accepted_outcome=first_outcome,
        result={"value": "a"},
    )
    initial = GraphExecutionState(run_id=run.run_id, active_node_ids=("a",))
    decision = GraphEdgeDecision(
        edge_id="a-b",
        source_node_id="a",
        source_node_run_id=first_run.node_run_id,
        target_node_id="b",
        selected=True,
        cycle=0,
    )
    first_state = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=("b",),
        cycle=1,
        edge_decisions=(decision,),
    )
    first_commit = TraversalCommit.from_transition(
        graph_snapshot_hash=run.graph.content_hash,
        prior_state=initial,
        resulting_state=first_state,
        ordered_source_node_run_ids=(first_run.node_run_id,),
        accepted_outcomes=(first_outcome,),
        edge_decisions=(decision,),
        commit_sequence=1,
    )

    checkpointed = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=("b",),
        cycle=1,
        edge_decisions=(decision,),
        metadata={"hitl_answers": {"b": {"answer": "approved"}}},
    )
    second_outcome = _outcome("node-run-b", "attempt-b", {"value": "b"})
    second_run = NodeRun(
        node_run_id="node-run-b",
        run_id=run.run_id,
        node_id="b",
        ordinal=2,
        status=RunStatus.COMPLETED,
        finished_at=second_outcome.attempt_result.finished_at,
        accepted_outcome=second_outcome,
        result={"value": "b"},
    )
    checkpoint = TraversalCheckpoint.from_state(
        graph_snapshot_hash=run.graph.content_hash,
        state=checkpointed,
        ordered_source_node_run_ids=(second_run.node_run_id,),
        checkpoint_sequence=1,
    )
    final_state = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=(),
        cycle=2,
        edge_decisions=(decision,),
        metadata=checkpointed.metadata,
    )
    second_commit = TraversalCommit.from_transition(
        graph_snapshot_hash=run.graph.content_hash,
        prior_state=checkpointed,
        resulting_state=final_state,
        ordered_source_node_run_ids=(second_run.node_run_id,),
        accepted_outcomes=(second_outcome,),
        edge_decisions=(),
        commit_sequence=2,
        prior_commit_id=first_commit.traversal_commit_id,
        checkpoint_id=checkpoint.traversal_checkpoint_id,
    )
    return (
        run,
        (first_run, second_run),
        final_state,
        checkpoint,
        (first_commit, second_commit),
    )


def test_checkpoint_bridges_nonadvancing_state_between_commits() -> None:
    run, node_runs, final_state, checkpoint, commits = _history()

    record = DurableRunRecord(
        run=run,
        graph_state=final_state,
        node_runs=node_runs,
        traversal_checkpoints=(checkpoint,),
        traversal_commits=commits,
    )

    assert record.latest_traversal_checkpoint == checkpoint
    assert record.latest_traversal_commit == commits[-1]
    assert commits[-1].checkpoint_id == checkpoint.traversal_checkpoint_id


def test_commit_rejects_missing_checkpoint_bridge() -> None:
    run, node_runs, final_state, _checkpoint, commits = _history()

    with pytest.raises(ValueError, match="checkpoint bridge must be persisted"):
        DurableRunRecord(
            run=run,
            graph_state=final_state,
            node_runs=node_runs,
            traversal_commits=commits,
        )
