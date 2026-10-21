"""Unit tests for workspace store-boundary helpers (#364, P0.8 diff coverage)."""

from __future__ import annotations

import pytest

from maistro.projects.scope import Project, ProjectScopeDenied
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces.authorization import WorkspaceAuthorizationDenied
from maistro.workspaces.store import InMemoryWorkspaceStore
from maistro.workspaces.store_boundary import (
    is_blank_principal,
    require_project_view,
    require_workspace_view,
)


@pytest.mark.parametrize(
    "principal",
    [None, "", "   ", 0, []],
)
def test_is_blank_principal(principal: object) -> None:
    assert is_blank_principal(principal)


def test_is_blank_principal_accepts_non_blank() -> None:
    assert not is_blank_principal("alice")


async def test_require_project_view_rejects_blank_principal() -> None:
    project = Project(
        workspace_id="ws-1",
        name="Scoped",
        parent_project_id="root-1",
    )
    stores = InMemoryWorkspaceStore(project_store=InMemoryProjectScopeStore())
    with pytest.raises(ProjectScopeDenied, match="Project not found"):
        await require_project_view(project, stores, "   ")


async def test_require_project_view_wraps_workspace_denial() -> None:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    projects.bind_workspace_store(workspaces)
    owner_ws = await workspaces.create(creator_user_id="owner", name="WS")
    root = await projects.root_for_workspace(owner_ws.workspace_id)
    project = await projects.create(
        workspace_id=owner_ws.workspace_id,
        parent_project_id=root.project_id,
        name="Child",
    )
    with pytest.raises(ProjectScopeDenied, match="Project not found"):
        await require_project_view(project, workspaces, "outsider")


async def test_require_workspace_view_passes_for_member() -> None:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    projects.bind_workspace_store(workspaces)
    workspace = await workspaces.create(creator_user_id="owner", name="WS")
    await require_workspace_view(workspaces, workspace.workspace_id, "owner")


async def test_require_workspace_view_denies_outsider() -> None:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    projects.bind_workspace_store(workspaces)
    workspace = await workspaces.create(creator_user_id="owner", name="WS")
    with pytest.raises(WorkspaceAuthorizationDenied):
        await require_workspace_view(workspaces, workspace.workspace_id, "outsider")
