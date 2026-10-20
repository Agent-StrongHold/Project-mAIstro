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


async def require_workspace_administer(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    principal_id: str,
) -> None:
    await WorkspaceAuthorizer(workspace_store).require(
        principal_id, workspace_id, WorkspaceAction.ADMINISTER
    )


async def authorize_workspace_view(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    principal_id: str | None,
) -> None:
    """Enforce VIEW when the caller supplied an acting principal.

    ``None`` is the explicit internal/system call shape used by bootstrap and
    migration code that owns the store rather than acting for a user. Product
    consumers always carry a principal, so they cannot take this branch by
    accident (#1150). A blank principal is a refusal, not an absent one.
    """
    if principal_id is None:
        return
    if is_blank_principal(principal_id):
        raise WorkspaceAuthorizationDenied
    await require_workspace_view(workspace_store, workspace_id, principal_id)


async def authorize_workspace_administer(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    principal_id: str | None,
) -> None:
    """Enforce ADMINISTER when the caller supplied an acting principal."""
    if principal_id is None:
        return
    if is_blank_principal(principal_id):
        raise WorkspaceAuthorizationDenied
    await require_workspace_administer(workspace_store, workspace_id, principal_id)


async def authorize_membership_removal(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    *,
    user_id: str,
    principal_id: str | None,
) -> None:
    """Authorize removing ``user_id``'s membership as ``principal_id``.

    Leaving a Workspace is deliberately not an owner-only action, so a
    principal removing themselves needs VIEW; removing anyone else needs
    ADMINISTER. Both answers still come from `WorkspaceAuthorizer`, so the
    self-service exception cannot become a second authorization path.
    """
    if principal_id is None:
        return
    if is_blank_principal(principal_id):
        raise WorkspaceAuthorizationDenied
    if principal_id == user_id:
        await require_workspace_view(workspace_store, workspace_id, principal_id)
        return
    await require_workspace_administer(workspace_store, workspace_id, principal_id)


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


async def require_project_administer(
    project: Project,
    workspace_store: WorkspaceStore,
    principal_id: str,
) -> None:
    """Require Workspace ADMINISTER for a Project-scoped write.

    A Project's authority is its Workspace's: there is no second Project
    owner role to resolve. Missing, foreign and blank-principal cases all
    read as one `ProjectScopeDenied`, so a refusal never discloses that a
    Project id exists (#1150).
    """
    if is_blank_principal(principal_id):
        raise ProjectScopeDenied("Project not found")
    try:
        await require_workspace_administer(workspace_store, project.workspace_id, principal_id)
    except WorkspaceAuthorizationDenied as exc:
        raise ProjectScopeDenied("Project not found") from exc


__all__ = [
    "ProjectScopeDenied",
    "WorkspaceAuthorizationDenied",
    "authorize_membership_removal",
    "authorize_workspace_administer",
    "authorize_workspace_view",
    "is_blank_principal",
    "require_project_administer",
    "require_project_view",
    "require_workspace_administer",
    "require_workspace_view",
]
