"""Unit tests for RunStoreBoundary (#364, P0.8 diff coverage)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import Attempt, AttemptStatus, NodeRun, Run
from maistro.runs.scoped_reads import RunNotVisible
from maistro.runs.store import InMemoryRunStore
from maistro.runs.store_boundary import RunStoreBoundary, require_admitted_actor
from maistro.workspaces.store import InMemoryWorkspaceStore


@pytest.mark.parametrize("actor", [None, "", "   "])
def test_require_admitted_actor_rejects_blank(actor: str | None) -> None:
    with pytest.raises(ValueError, match="actor_principal_id is required"):
        require_admitted_actor(actor)


def test_require_admitted_actor_strips() -> None:
    assert require_admitted_actor("  alice  ") == "alice"


async def _world() -> tuple[
    InMemoryRunStore, InMemoryWorkspaceStore, InMemoryProjectScopeStore, Run, NodeRun, Attempt
]:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    projects.bind_workspace_store(workspaces)
    runs = InMemoryRunStore(project_store=projects, workspace_store=workspaces)
    workspace = await workspaces.create(creator_user_id="owner", name="WS")
    root = await projects.root_for_workspace(workspace.workspace_id)
    project = await projects.create(
        workspace_id=workspace.workspace_id,
        parent_project_id=root.project_id,
        name="Work",
    )
    graph = Graph(
        workspace_id=workspace.workspace_id,
        project_id=project.project_id,
        name="scoped",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await runs.create_run(graph, actor_principal_id="owner")
    node_run = await runs.create_node_run(run.run_id, node_id="node-1")
    attempt = await runs.create_attempt(node_run.node_run_id)
    return runs, workspaces, projects, run, node_run, attempt


async def test_run_store_boundary_require_run() -> None:
    runs, workspaces, projects, run, _, _ = await _world()
    boundary = RunStoreBoundary(runs, workspaces, projects)
    found = await boundary.require_run(run.run_id, principal_id="owner")
    assert found.run_id == run.run_id


async def test_run_store_boundary_require_node_run_success() -> None:
    runs, workspaces, projects, _, node_run, _ = await _world()
    boundary = RunStoreBoundary(runs, workspaces, projects)
    found = await boundary.require_node_run(node_run.node_run_id, principal_id="owner")
    assert found.node_run_id == node_run.node_run_id


async def test_run_store_boundary_require_attempt_success() -> None:
    runs, workspaces, projects, _, _, attempt = await _world()
    boundary = RunStoreBoundary(runs, workspaces, projects)
    found = await boundary.require_attempt(attempt.attempt_id, principal_id="owner")
    assert found.attempt_id == attempt.attempt_id


async def test_run_store_boundary_require_node_run_missing() -> None:
    runs, workspaces, projects, _, _, _ = await _world()
    boundary = RunStoreBoundary(runs, workspaces, projects)
    with pytest.raises(RunNotVisible):
        await boundary.require_node_run("missing-node-run", principal_id="owner")


async def test_run_store_boundary_require_attempt_missing() -> None:
    runs, workspaces, projects, _, _, _ = await _world()
    boundary = RunStoreBoundary(runs, workspaces, projects)
    with pytest.raises(RunNotVisible):
        await boundary.require_attempt("missing-attempt", principal_id="owner")


async def test_run_store_boundary_require_attempt_orphan_node_run() -> None:
    runs = MagicMock()
    runs.get_attempt = AsyncMock(
        return_value=Attempt(
            attempt_id="attempt-1",
            node_run_id="missing-node-run",
            ordinal=1,
            status=AttemptStatus.CREATED,
        )
    )
    runs.get_node_run = AsyncMock(return_value=None)
    boundary = RunStoreBoundary(runs, MagicMock(), MagicMock())
    with pytest.raises(RunNotVisible):
        await boundary.require_attempt("attempt-1", principal_id="owner")
