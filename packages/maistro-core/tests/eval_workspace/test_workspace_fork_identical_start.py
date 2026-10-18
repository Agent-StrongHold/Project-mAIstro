"""Fork and restore: identical-start-state branches for matched comparisons.

The guarantee under test: two forks of the same snapshot are provably an
identical-start-state matched pair (same environment digest AND same recorded
start-state digest), and the substrate refuses every operation that would
manufacture a fake pair -- forking into a different environment, restoring a
snapshot from another environment, or forking a workspace with no recorded
start state.
"""

from __future__ import annotations

import pytest

from maistro.eval_workspace import (
    EMPTY_FIXTURES,
    EnvironmentMismatchError,
    EvalWorkspaceService,
    FixtureEntry,
    FixtureManifest,
    WorkspaceStateError,
    start_states_match,
)

from .conftest import fixture_digest, sandbox_config


def _fixtures(content: bytes) -> FixtureManifest:
    return FixtureManifest(
        entries=(FixtureEntry(name="task.json", content_sha256=fixture_digest(content)),)
    )


def _provision(
    service: EvalWorkspaceService,
    *,
    workspace_id: str,
    fixtures: FixtureManifest = EMPTY_FIXTURES,
) -> str:
    workspace = service.provision(
        workspace_id=workspace_id,
        project_id="proj-1",
        image="python:3.12-slim",
        sandbox=sandbox_config(),
        fixtures=fixtures,
        run_id="run-1",
        node_run_id="nr-1",
        attempt_id="att-1",
    )
    return service.activate(workspace.workspace_env_id).workspace_env_id


def test_fork_carries_parent_lineage_and_recorded_start_state(
    service: EvalWorkspaceService,
) -> None:
    parent = _provision(service, workspace_id="ws-parent")
    snap = service.snapshot(parent, state=b"state-v1", label="before eval", run_id="run-1")
    child = service.fork_from_workspace(
        parent,
        workspace_id="ws-child",
        project_id="proj-1",
        run_id="run-2",
    )
    assert child.parent_workspace_env_id == parent
    assert child.forked_from_snapshot_id == snap.snapshot_id
    assert child.environment_digest == service.get(parent).environment_digest
    assert child.start_state_digest == snap.content_digest
    assert child.produced_run_id == "run-2"
    assert [ws.workspace_env_id for ws in service.children_of(parent)] == [child.workspace_env_id]


def test_two_forks_of_one_snapshot_are_an_identical_start_pair(
    service: EvalWorkspaceService,
) -> None:
    parent = _provision(service, workspace_id="ws-parent")
    service.snapshot(parent, state=b"identical-start")
    a = service.fork_from_workspace(
        parent, workspace_id="ws-a", project_id="proj-1", run_id="run-a"
    )
    b = service.fork_from_workspace(
        parent, workspace_id="ws-b", project_id="proj-1", run_id="run-b"
    )
    assert start_states_match(a, b)
    # The comparison is symmetric and refuses fresh, unproven workspaces:
    fresh = _provision(service, workspace_id="ws-fresh")
    assert not start_states_match(a, service.get(fresh))


def test_fork_without_a_recorded_start_state_is_refused(
    service: EvalWorkspaceService,
) -> None:
    parent = _provision(service, workspace_id="ws-parent")
    with pytest.raises(WorkspaceStateError, match="no snapshots"):
        service.fork_from_workspace(parent, workspace_id="ws-child", project_id="proj-1")


def test_fork_targets_can_pick_a_non_latest_fork_point(
    service: EvalWorkspaceService,
) -> None:
    parent = _provision(service, workspace_id="ws-parent")
    first = service.snapshot(parent, state=b"early")
    service.snapshot(parent, state=b"late")
    child = service.fork_from_snapshot(
        first.snapshot_id, workspace_id="ws-child", project_id="proj-1"
    )
    assert child.start_state_digest == first.content_digest


def test_restore_into_a_different_environment_is_refused(
    service: EvalWorkspaceService,
) -> None:
    """A snapshot from another environment would fake comparability."""
    alpha = _provision(service, workspace_id="ws-alpha", fixtures=_fixtures(b"alpha"))
    snap = service.snapshot(alpha, state=b"alpha-state")
    beta = _provision(service, workspace_id="ws-beta", fixtures=_fixtures(b"beta"))
    with pytest.raises(EnvironmentMismatchError, match="fake an identical start"):
        service.restore(beta, snap.snapshot_id)


def test_restore_within_one_environment_updates_start_state(
    service: EvalWorkspaceService,
) -> None:
    parent = _provision(service, workspace_id="ws-parent")
    snap = service.snapshot(parent, state=b"checkpoint-1")
    child = service.fork_from_workspace(parent, workspace_id="ws-child", project_id="proj-1")
    drifted = service.snapshot(child.workspace_env_id, state=b"child drifted")
    restored = service.restore(child.workspace_env_id, snap.snapshot_id, run_id="run-9")
    assert restored.start_state_digest == snap.content_digest
    assert restored.start_state_digest != drifted.content_digest


def test_retired_workspaces_cannot_fork_snapshot_or_restore(
    service: EvalWorkspaceService,
) -> None:
    parent = _provision(service, workspace_id="ws-parent")
    snap = service.snapshot(parent, state=b"s")
    service.archive(parent)
    with pytest.raises(WorkspaceStateError, match="retired"):
        service.snapshot(parent, state=b"more")
    with pytest.raises(WorkspaceStateError, match="retired"):
        service.restore(parent, snap.snapshot_id)
    with pytest.raises(WorkspaceStateError, match="retired"):
        service.fork_from_workspace(parent, workspace_id="ws-c", project_id="proj-1")
