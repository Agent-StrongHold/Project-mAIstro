"""CONNECT coverage for durable traversal helpers (#2314)."""

from __future__ import annotations

from maistro.graph.durable_runs.executor import (
    _drain_steering_queue,
    _prepare_traversal_blackboard,
)


def test_drain_steering_queue_moves_strings_onto_steering() -> None:
    metadata: dict[str, object] = {
        "_steering_queue": ["keep going", "", 42, "focus on reviews"],
        "shared_context": {"goal_id": "g1"},
    }
    _drain_steering_queue(metadata)
    assert "_steering_queue" not in metadata
    assert metadata["_steering"] == ["keep going", "focus on reviews"]
    assert metadata["shared_context"] == {"goal_id": "g1"}


def test_drain_steering_queue_noop_for_empty_or_non_list() -> None:
    empty: dict[str, object] = {"_steering_queue": []}
    _drain_steering_queue(empty)
    assert "_steering" not in empty
    assert "_steering_queue" not in empty

    other: dict[str, object] = {"_steering_queue": "not-a-list"}
    _drain_steering_queue(other)
    assert "_steering" not in other
    assert "_steering_queue" not in other


def test_prepare_traversal_blackboard_drains_steering_and_keeps_shared_context() -> None:
    snapshot = {
        "task_objective": "ship",
        "workspace": "ws",
        "metadata": {
            "_steering_queue": ["nudge"],
            "shared_context": {"audience": "bakers"},
        },
        "node_annotations": {"a": "1"},
    }
    board = _prepare_traversal_blackboard(snapshot)
    assert board.task_objective == "ship"
    assert board.workspace == "ws"
    assert board.metadata["shared_context"] == {"audience": "bakers"}
    assert board.metadata["_steering"] == ["nudge"]
    assert "_steering_queue" not in board.metadata
    assert board.node_annotations == {"a": "1"}
