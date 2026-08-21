from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.graph import Graph, Node
from maistro.runs import (
    Attempt,
    AttemptStatus,
    GraphSnapshot,
    InvalidLifecycleTransition,
    NodeRun,
    Run,
    RunStatus,
    transition_attempt,
    transition_node_run,
    transition_run,
)


def _graph() -> Graph:
    return Graph(
        graph_id="graph-1",
        workspace_id="workspace-1",
        project_id="project-1",
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


def test_graph_snapshot_is_stable_after_mutable_graph_changes() -> None:
    graph = _graph()
    snapshot = GraphSnapshot.from_graph(graph)

    graph.nodes[0].parameters["model"] = "changed-later"

    materialized = snapshot.materialize()
    assert materialized.nodes[0].parameters == {}
    assert snapshot.content_hash != graph.content_hash
    assert snapshot.project_id == "project-1"


def test_run_requires_graph_snapshot_from_same_workspace_and_project() -> None:
    snapshot = GraphSnapshot.from_graph(_graph())

    with pytest.raises(ValueError, match="same Workspace"):
        Run(
            workspace_id="workspace-2",
            project_id="project-1",
            graph=snapshot,
        )

    with pytest.raises(ValueError, match="same Project"):
        Run(
            workspace_id="workspace-1",
            project_id="project-2",
            graph=snapshot,
        )


def test_run_transition_sets_start_and_finish_timestamps() -> None:
    created_at = datetime(2026, 8, 13, 12, tzinfo=UTC)
    run = Run(
        workspace_id="workspace-1",
        project_id="project-1",
        graph=GraphSnapshot.from_graph(_graph()),
        created_at=created_at,
        updated_at=created_at,
    )

    queued = transition_run(run, RunStatus.QUEUED, at=created_at + timedelta(seconds=1))
    running = transition_run(queued, RunStatus.RUNNING, at=created_at + timedelta(seconds=2))
    completed = transition_run(
        running,
        RunStatus.COMPLETED,
        at=created_at + timedelta(seconds=3),
        result={"ok": True},
    )

    assert run.status is RunStatus.CREATED
    assert running.started_at == created_at + timedelta(seconds=2)
    assert completed.finished_at == created_at + timedelta(seconds=3)
    assert completed.result == {"ok": True}
    assert completed.project_id == "project-1"

    with pytest.raises(InvalidLifecycleTransition, match="completed -> running"):
        transition_run(completed, RunStatus.RUNNING)


def test_node_run_uses_same_logical_transition_rules() -> None:
    node_run = NodeRun(run_id="run-1", node_id="node-1", ordinal=1)
    queued = transition_node_run(node_run, RunStatus.QUEUED)
    running = transition_node_run(queued, RunStatus.RUNNING)
    waiting = transition_node_run(running, RunStatus.WAITING)

    assert waiting.status is RunStatus.WAITING
    assert waiting.finished_at is None


def test_attempt_yield_is_terminal_physical_outcome() -> None:
    attempt = Attempt(node_run_id="node-run-1", ordinal=1)
    running = transition_attempt(attempt, AttemptStatus.RUNNING)
    yielded = transition_attempt(running, AttemptStatus.YIELDED)

    assert yielded.finished_at is not None
    with pytest.raises(InvalidLifecycleTransition, match="yielded -> running"):
        transition_attempt(yielded, AttemptStatus.RUNNING)
