"""Contract tests for graph-specific state kept outside canonical Run."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.graph.execution_state import GraphEdgeDecision, GraphExecutionState


def test_state_can_persist_multi_node_frontier() -> None:
    state = GraphExecutionState(
        run_id="run-1",
        active_node_ids=["left", "right"],
        cycle=2,
        visit_counts={"start": 1, "left": 1, "right": 1},
    )

    assert state.active_node_ids == ("left", "right")
    assert state.cycle == 2


def test_edge_decisions_distinguish_repeated_visits_to_same_edge() -> None:
    first = GraphEdgeDecision(
        edge_id="review-to-code",
        source_node_id="review",
        source_node_run_id="node-run-1",
        target_node_id="code",
        selected=True,
        cycle=1,
        condition="review.approved == False",
    )
    second = GraphEdgeDecision(
        edge_id="review-to-code",
        source_node_id="review",
        source_node_run_id="node-run-4",
        target_node_id="code",
        selected=False,
        cycle=3,
        condition="review.approved == False",
    )
    state = GraphExecutionState(
        run_id="run-1",
        edge_decisions=[first, second],
        visit_counts={"review": 2},
    )

    assert [decision.source_node_run_id for decision in state.edge_decisions] == [
        "node-run-1",
        "node-run-4",
    ]
    assert state.edge_decisions[0].selected is True
    assert state.edge_decisions[1].selected is False


def test_duplicate_edge_decision_for_same_source_run_is_rejected() -> None:
    first = GraphEdgeDecision(
        edge_id="review-to-code",
        source_node_id="review",
        source_node_run_id="node-run-1",
        target_node_id="code",
        selected=True,
        cycle=1,
    )
    contradictory = first.model_copy(update={"selected": False})

    with pytest.raises(
        ValidationError,
        match="edge_decisions must be unique per source_node_run_id and edge_id",
    ):
        GraphExecutionState(
            run_id="run-1",
            edge_decisions=[first, contradictory],
        )


def test_state_round_trips_blackboard_and_decisions() -> None:
    state = GraphExecutionState(
        run_id="run-1",
        active_node_ids=["review"],
        blackboard_snapshot={"metadata": {"answer": 42, "history": ["draft", "review"]}},
        edge_decisions=[
            GraphEdgeDecision(
                edge_id="e1",
                source_node_id="code",
                source_node_run_id="node-run-2",
                target_node_id="review",
                selected=True,
                cycle=1,
            )
        ],
    )

    restored = GraphExecutionState.model_validate_json(state.model_dump_json())

    assert restored == state


def test_state_can_seed_transition_from_frozen_checkpoint_data() -> None:
    checkpointed = GraphExecutionState(
        run_id="run-1",
        blackboard_snapshot={"review": {"history": ["draft", "approved"]}},
        metadata={
            "hitl_answers": {
                "review": {"answer": "approved", "tags": ["human", "approved"]},
            },
        },
    )

    transitioned = GraphExecutionState(
        run_id=checkpointed.run_id,
        blackboard_snapshot=checkpointed.blackboard_snapshot,
        metadata=checkpointed.metadata,
    )

    assert transitioned.blackboard_snapshot == checkpointed.blackboard_snapshot
    assert transitioned.metadata == checkpointed.metadata


def test_state_rejects_non_json_checkpoint_values() -> None:
    with pytest.raises(ValidationError, match="must contain only JSON values"):
        GraphExecutionState(
            run_id="run-1",
            blackboard_snapshot={"bad": {"not", "json"}},
        )

    with pytest.raises(ValidationError, match="finite JSON numbers"):
        GraphExecutionState(
            run_id="run-1",
            metadata={"score": float("nan")},
        )


def test_state_cannot_be_mutated_after_validation() -> None:
    state = GraphExecutionState(
        run_id="run-1",
        active_node_ids=["worker"],
        visit_counts={"worker": 1},
        blackboard_snapshot={"metadata": {"answer": 42}},
    )

    with pytest.raises(ValidationError):
        state.cycle = -1
    with pytest.raises(TypeError):
        state.visit_counts["worker"] = -1  # type: ignore[index]
    with pytest.raises(TypeError):
        state.blackboard_snapshot["metadata"]["answer"] = 0


def test_active_frontier_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValidationError, match="active_node_ids must not contain duplicates"):
        GraphExecutionState(run_id="run-1", active_node_ids=["worker", "worker"])


def test_edge_decision_is_immutable_execution_fact() -> None:
    decision = GraphEdgeDecision(
        edge_id="e1",
        source_node_id="start",
        source_node_run_id="node-run-1",
        target_node_id="next",
        selected=True,
        cycle=0,
    )

    with pytest.raises(ValidationError):
        decision.selected = False


def test_graph_state_does_not_duplicate_universal_lifecycle_fields() -> None:
    fields = GraphExecutionState.model_fields

    assert "status" not in fields
    assert "project_id" not in fields
    assert "workspace_id" not in fields
    assert "attempts" not in fields
    assert "deadline_at" not in fields
    assert "result" not in fields
    assert "error" not in fields
