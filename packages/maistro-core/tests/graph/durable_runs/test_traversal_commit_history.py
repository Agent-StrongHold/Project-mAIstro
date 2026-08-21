from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.graph import (
    Edge,
    Graph,
    GraphEdgeDecision,
    GraphExecutionState,
    Node,
    TraversalCommit,
)
from maistro.graph.durable_runs import DurableRunRecord
from maistro.graph.traversal_commit import edge_decision_id
from maistro.runs import (
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    GraphSnapshot,
    NodeRun,
    Run,
    RunStatus,
)


def _accepted_outcome(
    *,
    node_run_id: str,
    attempt_id: str,
    result: object,
) -> AcceptedNodeOutcome:
    return AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult(
            attempt_id=attempt_id,
            node_run_id=node_run_id,
            ordinal=1,
            status=AttemptStatus.COMPLETED,
            result=result,
            finished_at=datetime(2026, 8, 16, 10, 0, tzinfo=UTC),
        ),
        logical_status=RunStatus.COMPLETED,
        result=result,
    )


def _fixture() -> tuple[Run, NodeRun, GraphExecutionState, TraversalCommit]:
    graph = Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Traversal commits",
        nodes=[
            Node(node_id="a", node_type="agent"),
            Node(node_id="b", node_type="agent"),
        ],
        edges=[Edge(from_node="a", to_node="b")],
    )
    run = Run(
        run_id="run-1",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.RUNNING,
    )
    outcome = _accepted_outcome(
        node_run_id="node-run-a",
        attempt_id="attempt-a",
        result={"value": 7},
    )
    node_run = NodeRun(
        node_run_id="node-run-a",
        run_id=run.run_id,
        node_id="a",
        ordinal=1,
        status=RunStatus.COMPLETED,
        finished_at=datetime(2026, 8, 16, 10, 1, tzinfo=UTC),
        accepted_outcome=outcome,
        result={"value": 7},
    )
    prior = GraphExecutionState(run_id=run.run_id, active_node_ids=("a",))
    decision = GraphEdgeDecision(
        edge_id="edge-a-b",
        source_node_id="a",
        source_node_run_id=node_run.node_run_id,
        target_node_id="b",
        selected=True,
        cycle=0,
    )
    resulting = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=("b",),
        cycle=1,
        visit_counts={"a": 1},
        edge_decisions=(decision,),
    )
    commit = TraversalCommit.from_transition(
        graph_snapshot_hash=run.graph.content_hash,
        prior_state=prior,
        resulting_state=resulting,
        ordered_source_node_run_ids=(node_run.node_run_id,),
        accepted_outcomes=(outcome,),
        edge_decisions=(decision,),
        commit_sequence=1,
    )
    return run, node_run, resulting, commit


def test_durable_record_accepts_verified_commit_chain_and_exposes_latest() -> None:
    run, node_run, state, commit = _fixture()

    record = DurableRunRecord(
        run=run,
        graph_state=state,
        node_runs=(node_run,),
        traversal_commits=(commit,),
        version=4,
    )

    assert record.latest_traversal_commit == commit


def test_post_commit_checkpoint_metadata_can_evolve_without_new_traversal_commit() -> None:
    run, node_run, state, commit = _fixture()
    checkpointed = state.model_copy(
        update={
            "metadata": {
                "hitl_answers": {"b": {"answer": "approved"}},
                "checkpoint_note": "persisted after traversal advancement",
            }
        }
    )

    record = DurableRunRecord(
        run=run,
        graph_state=checkpointed,
        node_runs=(node_run,),
        traversal_commits=(commit,),
    )

    assert record.latest_traversal_commit == commit
    assert record.graph_state.metadata["checkpoint_note"] == "persisted after traversal advancement"


def test_latest_commit_frontier_must_match_live_traversal_frontier() -> None:
    run, node_run, state, commit = _fixture()
    drifted = state.model_copy(update={"active_node_ids": ("a",)})

    with pytest.raises(ValueError, match="frontier"):
        DurableRunRecord(
            run=run,
            graph_state=drifted,
            node_runs=(node_run,),
            traversal_commits=(commit,),
        )


def test_adjacent_commits_must_link_resulting_and_prior_state_hashes() -> None:
    run, first_node_run, first_state, first_commit = _fixture()
    second_outcome = _accepted_outcome(
        node_run_id="node-run-b",
        attempt_id="attempt-b",
        result={"done": True},
    )
    second_node_run = NodeRun(
        node_run_id="node-run-b",
        run_id=run.run_id,
        node_id="b",
        ordinal=2,
        status=RunStatus.COMPLETED,
        finished_at=datetime(2026, 8, 16, 10, 2, tzinfo=UTC),
        accepted_outcome=second_outcome,
        result={"done": True},
    )
    unrelated_prior = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=("b",),
        cycle=99,
        edge_decisions=first_state.edge_decisions,
    )
    final_state = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=(),
        cycle=100,
        edge_decisions=first_state.edge_decisions,
    )
    second_commit = TraversalCommit.from_transition(
        graph_snapshot_hash=run.graph.content_hash,
        prior_state=unrelated_prior,
        resulting_state=final_state,
        ordered_source_node_run_ids=(second_node_run.node_run_id,),
        accepted_outcomes=(second_outcome,),
        edge_decisions=(),
        commit_sequence=2,
        prior_commit_id=first_commit.traversal_commit_id,
    )

    with pytest.raises(ValueError, match="adjacent TraversalCommits"):
        DurableRunRecord(
            run=run,
            graph_state=final_state,
            node_runs=(first_node_run, second_node_run),
            traversal_commits=(first_commit, second_commit),
        )


def test_commit_outcome_identity_must_match_persisted_accepted_node_outcome() -> None:
    run, node_run, state, commit = _fixture()
    assert node_run.accepted_outcome is not None
    altered_outcome = node_run.accepted_outcome.model_copy(update={"result": {"value": 8}})
    altered_node_run = node_run.model_copy(
        update={"result": {"value": 8}, "accepted_outcome": altered_outcome}
    )

    with pytest.raises(ValueError, match="outcome identities"):
        DurableRunRecord(
            run=run,
            graph_state=state,
            node_runs=(altered_node_run,),
            traversal_commits=(commit,),
        )


def test_commit_routing_decision_must_belong_to_commit_source_node_run() -> None:
    run, node_run, state, commit = _fixture()
    foreign_decision = GraphEdgeDecision(
        edge_id="edge-foreign",
        source_node_id="b",
        source_node_run_id="node-run-foreign",
        target_node_id="a",
        selected=True,
        cycle=1,
    )
    state_with_foreign_decision = state.model_copy(
        update={"edge_decisions": (*state.edge_decisions, foreign_decision)}
    )
    forged_commit = commit.model_copy(
        update={"edge_decision_ids": (edge_decision_id(foreign_decision),)}
    )

    with pytest.raises(ValueError, match="authoritative content"):
        DurableRunRecord(
            run=run,
            graph_state=state_with_foreign_decision,
            node_runs=(node_run,),
            traversal_commits=(forged_commit,),
        )


def test_commit_graph_snapshot_must_match_run_snapshot() -> None:
    _run, _node_run, _state, commit = _fixture()
    payload = commit.model_dump(mode="python")
    payload["graph_snapshot_hash"] = "different"
    payload["traversal_commit_id"] = commit.traversal_commit_id

    with pytest.raises(ValueError):
        TraversalCommit.model_validate(payload)
