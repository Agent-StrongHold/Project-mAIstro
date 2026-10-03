"""Shared scope enforcement at durable store boundaries (#364)."""

from __future__ import annotations

from maistro.projects.scope import Project, ProjectScopeDenied
from maistro.workspaces.authorization import (
    WorkspaceAction,
    WorkspaceAuthorizationDenied,
    WorkspaceAuthorizer,
)
from maistro.workspaces.store import WorkspaceStore


def is_blank_principal(principal_id: object) -> bool:
    return not isinstance(principal_id, str) or not principal_id.strip()


async def require_workspace_view(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    principal_id: str,
) -> None:
    await WorkspaceAuthorizer(workspace_store).require(
        principal_id, workspace_id, WorkspaceAction.VIEW
    )


async def require_project_view(
    project: Project,
    workspace_store: WorkspaceStore,
    principal_id: str,
) -> None:
    if is_blank_principal(principal_id):
        raise ProjectScopeDenied("Project not found")
    try:
        await require_workspace_view(workspace_store, project.workspace_id, principal_id)
    except WorkspaceAuthorizationDenied as exc:
        raise ProjectScopeDenied("Project not found") from exc


__all__ = [
    "ProjectScopeDenied",
    "WorkspaceAuthorizationDenied",
    "is_blank_principal",
    "require_project_view",
    "require_workspace_view",
]
