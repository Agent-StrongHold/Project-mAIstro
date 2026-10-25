"""The Project membership-write boundary's own refusal paths (#1150).

`authorize_membership_write` is the seam a store call reaches; these cases pin
the paths the stores cannot reach on their own because a store always passes a
principal it resolved. `None` is the documented internal shape, a blank
principal is a refusal, and a plain member cannot add an action they cannot
delegate -- the same rule the HTTP route applies, resolved at the store so a
caller that reaches the store directly cannot skip it.
"""

from __future__ import annotations

import pytest

from maistro.projects.authorization import authorize_membership_write
from maistro.projects.scope import Project, ProjectMembership, ProjectScopeDenied
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces.model import WorkspaceRole
from maistro.workspaces.store import InMemoryWorkspaceStore


def _stores() -> tuple[InMemoryProjectScopeStore, InMemoryWorkspaceStore]:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    projects.bind_workspace_store(workspaces)
    return projects, workspaces


def _membership(project_id: str) -> ProjectMembership:
    return ProjectMembership(
        workspace_id="ws",
        project_id=project_id,
        principal_id="target",
        grants={"read"},
    )


async def test_none_principal_is_the_internal_shape_and_needs_no_store() -> None:
    projects, workspaces = _stores()
    project = Project(workspace_id="ws", name="Scoped", parent_project_id="root")

    await authorize_membership_write(
        projects,
        project=project,
        workspace_store=workspaces,
        membership=_membership("project"),
        principal_id=None,
        replacement=True,
    )


async def test_blank_principal_is_a_refusal_not_an_absent_one() -> None:
    projects, workspaces = _stores()
    project = Project(workspace_id="ws", name="Scoped", parent_project_id="root")

    with pytest.raises(ProjectScopeDenied, match="Project not found"):
        await authorize_membership_write(
            projects,
            project=project,
            workspace_store=workspaces,
            membership=_membership("project"),
            principal_id="  ",
            replacement=True,
        )


async def test_a_member_who_cannot_delegate_the_action_is_refused() -> None:
    projects, workspaces = _stores()
    workspace = await workspaces.create(creator_user_id="owner", name="WS")
    await workspaces.set_membership(
        workspace.workspace_id, user_id="member", role=WorkspaceRole.MEMBER, principal_id="owner"
    )
    root = await projects.root_for_workspace(workspace.workspace_id)
    project = await projects.create(
        workspace_id=workspace.workspace_id,
        parent_project_id=root.project_id,
        name="Scoped",
    )

    with pytest.raises(ProjectScopeDenied, match="Project not found"):
        await authorize_membership_write(
            projects,
            project=project,
            workspace_store=workspaces,
            membership=ProjectMembership(
                workspace_id=workspace.workspace_id,
                project_id=project.project_id,
                principal_id="target",
                grants={"read"},
            ),
            principal_id="member",
            replacement=False,
        )
