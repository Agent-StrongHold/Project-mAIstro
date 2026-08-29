from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.graph import Graph, Node
from maistro.runs import (
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
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
from maistro.runs.lifecycle import settle_open_node_run, transition_path


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


# ── settling an open NodeRun (#226, ADR-082426-a47f) ───────────────


@pytest.mark.parametrize(
    "run_target",
    [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT],
)
def test_an_open_node_run_settles_to_cancelled_whatever_its_run_did(
    run_target: RunStatus,
) -> None:
    """The node did not itself succeed, fail or time out — something outside it
    ended the work. Mirroring the Run's status would invent a physical outcome
    the node never had."""
    node_run = transition_node_run(
        transition_node_run(NodeRun(run_id="run-1", node_id="node-1", ordinal=1), RunStatus.QUEUED),
        RunStatus.RUNNING,
    )

    settled = settle_open_node_run(node_run, run_target)

    assert settled.status is RunStatus.CANCELLED
    assert settled.finished_at is not None
    assert settled.error == f"cancelled because its Run terminalized as {run_target.value}"


def test_every_open_status_can_be_settled() -> None:
    """The cascade must not be able to fail part-way through because one node
    happened to be parked rather than running."""
    node_run = NodeRun(run_id="run-1", node_id="node-1", ordinal=1)
    queued = transition_node_run(node_run, RunStatus.QUEUED)
    running = transition_node_run(queued, RunStatus.RUNNING)
    for open_node_run in (
        node_run,
        queued,
        running,
        transition_node_run(running, RunStatus.WAITING),
    ):
        assert settle_open_node_run(open_node_run, RunStatus.FAILED).status is RunStatus.CANCELLED


def test_settling_supersedes_an_accepted_paused_outcome() -> None:
    """`NodeRun` validates that its status *is* its accepted outcome's logical
    status, so a settled node cannot keep an acceptance reading `paused` — the
    record would claim both at once. The evidence survives on the Attempt."""
    node_run = NodeRun(run_id="run-1", node_id="node-1", ordinal=1)
    running = transition_node_run(
        transition_node_run(node_run, RunStatus.QUEUED), RunStatus.RUNNING
    )
    attempt = transition_attempt(
        transition_attempt(
            Attempt(node_run_id=node_run.node_run_id, ordinal=1), AttemptStatus.RUNNING
        ),
        AttemptStatus.COMPLETED,
        result={"paused": "for a human"},
    )
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run.node_run_id,
        attempt_result=AttemptResult.from_attempt(attempt),
        logical_status=RunStatus.PAUSED,
        result={"paused": "for a human"},
    )
    paused = transition_node_run(
        running, RunStatus.PAUSED, result=outcome.result, accepted_outcome=outcome
    )
    assert paused.accepted_outcome is not None

    settled = settle_open_node_run(paused, RunStatus.CANCELLED)

    assert settled.status is RunStatus.CANCELLED
    assert settled.accepted_outcome is None


def test_settling_stamps_the_caller_s_clock() -> None:
    """So every node in one cascade carries the same `finished_at` as the Run,
    rather than a spread that reads like they ended at different moments."""
    at = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    node_run = NodeRun(run_id="run-1", node_id="node-1", ordinal=1)

    settled = settle_open_node_run(node_run, RunStatus.CANCELLED, at=at)

    assert settled.finished_at == at


def test_transition_path_is_empty_when_there_is_nothing_to_do() -> None:
    assert transition_path(RunStatus.RUNNING, RunStatus.RUNNING) == ()


def test_transition_path_returns_the_single_legal_edge() -> None:
    assert transition_path(RunStatus.QUEUED, RunStatus.RUNNING) == (RunStatus.RUNNING,)


def test_transition_path_walks_the_gap_rather_than_jumping_it() -> None:
    """A node answered out of a HITL pause has to reach COMPLETED through the
    statuses the table actually has edges for."""
    assert transition_path(RunStatus.PAUSED, RunStatus.COMPLETED) == (
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
    )


def test_transition_path_refuses_to_invent_an_exit_from_a_terminal_status() -> None:
    """Silently returning nothing here would hide a real disagreement between
    two records about work that is already finished."""
    with pytest.raises(ValueError, match="no legal transition path"):
        transition_path(RunStatus.COMPLETED, RunStatus.RUNNING)
