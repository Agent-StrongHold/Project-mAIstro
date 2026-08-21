from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from maistro.graph import (
    GraphEdgeDecision,
    GraphExecutionState,
    TraversalCheckpoint,
    TraversalCommit,
    accepted_outcome_id,
    edge_decision_id,
    graph_state_hash,
)
from maistro.runs import AcceptedNodeOutcome, AttemptResult, AttemptStatus


def _outcome(
    node_run_id: str,
    attempt_id: str = "attempt-1",
    result: object | None = None,
) -> AcceptedNodeOutcome:
    physical = AttemptResult(
        attempt_id=attempt_id,
        node_run_id=node_run_id,
        ordinal=1,
        status=AttemptStatus.COMPLETED,
        result={"value": node_run_id} if result is None else result,
        finished_at=datetime(2026, 8, 16, 9, 30, tzinfo=UTC),
    )
    return AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=physical,
        accepted_at=datetime(2026, 8, 16, 9, 31, tzinfo=UTC),
    )


def _decision(source_node_run_id: str = "nr-a") -> GraphEdgeDecision:
    return GraphEdgeDecision(
        edge_id="edge-a-b",
        source_node_id="a",
        source_node_run_id=source_node_run_id,
        target_node_id="b",
        selected=True,
        cycle=0,
    )


def test_graph_state_hash_is_deterministic_and_state_sensitive() -> None:
    state = GraphExecutionState(
        run_id="run-1",
        active_node_ids=("a",),
        visit_counts={"a": 1},
        blackboard_snapshot={"value": 1},
    )
    equivalent = GraphExecutionState.model_validate(state.model_dump(mode="json"))
    advanced = GraphExecutionState(
        run_id="run-1",
        active_node_ids=("b",),
        cycle=1,
        visit_counts={"a": 1},
        blackboard_snapshot={"value": 1},
    )

    assert graph_state_hash(state) == graph_state_hash(equivalent)
    assert graph_state_hash(state) != graph_state_hash(advanced)


def test_fact_identities_are_stable_across_equivalent_reconstruction() -> None:
    decision = _decision()
    assert edge_decision_id(decision) == edge_decision_id(
        GraphEdgeDecision.model_validate(decision.model_dump(mode="json"))
    )

    first = _outcome("nr-a")
    later_acceptance = AcceptedNodeOutcome(
        node_run_id=first.node_run_id,
        attempt_result=first.attempt_result,
        accepted_at=first.accepted_at + timedelta(minutes=5),
    )
    assert accepted_outcome_id(first) == accepted_outcome_id(later_acceptance)


def test_accepted_outcome_identity_supports_json_serializable_typed_values() -> None:
    outcome = _outcome(
        "nr-a",
        result={
            "observed_at": datetime(2026, 8, 16, 9, 30, tzinfo=UTC),
            "id": UUID("12345678-1234-5678-1234-567812345678"),
        },
    )

    assert len(accepted_outcome_id(outcome)) == 64


def test_same_transition_reconstructs_same_content_addressed_commit() -> None:
    prior = GraphExecutionState(run_id="run-1", active_node_ids=("a",))
    resulting = GraphExecutionState(
        run_id="run-1",
        active_node_ids=("b",),
        cycle=1,
        visit_counts={"a": 1},
        edge_decisions=(_decision(),),
    )
    outcome = _outcome("nr-a")

    first = TraversalCommit.from_transition(
        graph_snapshot_hash="graph-hash",
        prior_state=prior,
        resulting_state=resulting,
        ordered_source_node_run_ids=("nr-a",),
        accepted_outcomes=(outcome,),
        edge_decisions=(_decision(),),
        commit_sequence=1,
    )
    reconstructed = TraversalCommit.from_transition(
        graph_snapshot_hash="graph-hash",
        prior_state=prior,
        resulting_state=resulting,
        ordered_source_node_run_ids=("nr-a",),
        accepted_outcomes=(outcome,),
        edge_decisions=(_decision(),),
        commit_sequence=1,
    )

    assert first.traversal_commit_id == reconstructed.traversal_commit_id
    assert first.prior_state_hash == graph_state_hash(prior)
    assert first.resulting_state_hash == graph_state_hash(resulting)
    assert first.resulting_frontier == ("b",)


def test_transition_requires_accepted_outcomes_in_source_visit_order() -> None:
    prior = GraphExecutionState(run_id="run-1", active_node_ids=("a", "c"))
    resulting = GraphExecutionState(run_id="run-1", active_node_ids=("b",))

    with pytest.raises(ValueError, match="deterministic order"):
        TraversalCommit.from_transition(
            graph_snapshot_hash="graph-hash",
            prior_state=prior,
            resulting_state=resulting,
            ordered_source_node_run_ids=("nr-a", "nr-c"),
            accepted_outcomes=(_outcome("nr-c", "attempt-c"), _outcome("nr-a")),
            edge_decisions=(),
            commit_sequence=1,
        )


def test_transition_rejects_routing_decision_from_other_visit() -> None:
    prior = GraphExecutionState(run_id="run-1", active_node_ids=("a",))
    wrong = _decision("nr-other")
    resulting = GraphExecutionState(
        run_id="run-1",
        active_node_ids=("b",),
        edge_decisions=(wrong,),
    )

    with pytest.raises(ValueError, match="source NodeRuns"):
        TraversalCommit.from_transition(
            graph_snapshot_hash="graph-hash",
            prior_state=prior,
            resulting_state=resulting,
            ordered_source_node_run_ids=("nr-a",),
            accepted_outcomes=(_outcome("nr-a"),),
            edge_decisions=(wrong,),
            commit_sequence=1,
        )


def test_transition_requires_supplied_decisions_to_be_exact_resulting_delta() -> None:
    prior = GraphExecutionState(run_id="run-1", active_node_ids=("a",))
    recorded = _decision()
    resulting = GraphExecutionState(
        run_id="run-1",
        active_node_ids=("b",),
        edge_decisions=(recorded,),
    )

    with pytest.raises(ValueError, match="exactly match"):
        TraversalCommit.from_transition(
            graph_snapshot_hash="graph-hash",
            prior_state=prior,
            resulting_state=resulting,
            ordered_source_node_run_ids=("nr-a",),
            accepted_outcomes=(_outcome("nr-a"),),
            edge_decisions=(),
            commit_sequence=1,
        )


def test_noninitial_commit_requires_prior_commit_identity() -> None:
    prior = GraphExecutionState(run_id="run-1", active_node_ids=("a",))
    resulting = GraphExecutionState(run_id="run-1", active_node_ids=())

    with pytest.raises(ValueError, match="prior_commit_id"):
        TraversalCommit.from_transition(
            graph_snapshot_hash="graph-hash",
            prior_state=prior,
            resulting_state=resulting,
            ordered_source_node_run_ids=("nr-a",),
            accepted_outcomes=(_outcome("nr-a"),),
            edge_decisions=(),
            commit_sequence=2,
        )


def test_initial_commit_rejects_prior_commit_identity() -> None:
    prior = GraphExecutionState(run_id="run-1", active_node_ids=("a",))
    resulting = GraphExecutionState(run_id="run-1", active_node_ids=())

    with pytest.raises(ValueError, match="initial TraversalCommit"):
        TraversalCommit.from_transition(
            graph_snapshot_hash="graph-hash",
            prior_state=prior,
            resulting_state=resulting,
            ordered_source_node_run_ids=("nr-a",),
            accepted_outcomes=(_outcome("nr-a"),),
            edge_decisions=(),
            commit_sequence=1,
            prior_commit_id="unexpected",
        )


def test_paused_visit_has_nonadvancing_checkpoint_evidence() -> None:
    paused = GraphExecutionState(
        run_id="run-1",
        active_node_ids=("human-review",),
        metadata={"pause": {"reason": "approval"}},
    )

    checkpoint = TraversalCheckpoint.from_state(
        graph_snapshot_hash="graph-hash",
        state=paused,
        ordered_source_node_run_ids=("nr-human",),
        checkpoint_sequence=1,
        checkpoint_id="cp-1",
    )
    reconstructed = TraversalCheckpoint.from_state(
        graph_snapshot_hash="graph-hash",
        state=paused,
        ordered_source_node_run_ids=("nr-human",),
        checkpoint_sequence=1,
        checkpoint_id="cp-1",
    )

    assert checkpoint.traversal_checkpoint_id == reconstructed.traversal_checkpoint_id
    assert checkpoint.state_hash == graph_state_hash(paused)
    assert checkpoint.ordered_source_node_run_ids == ("nr-human",)


def test_content_address_detects_tampered_authoritative_transition() -> None:
    prior = GraphExecutionState(run_id="run-1", active_node_ids=("a",))
    resulting = GraphExecutionState(run_id="run-1", active_node_ids=("b",))
    commit = TraversalCommit.from_transition(
        graph_snapshot_hash="graph-hash",
        prior_state=prior,
        resulting_state=resulting,
        ordered_source_node_run_ids=("nr-a",),
        accepted_outcomes=(_outcome("nr-a"),),
        edge_decisions=(),
        commit_sequence=1,
    )
    payload = commit.model_dump(mode="python")
    payload["resulting_state_hash"] = "tampered"

    with pytest.raises(ValueError, match="identity does not match"):
        TraversalCommit.model_validate(payload)
