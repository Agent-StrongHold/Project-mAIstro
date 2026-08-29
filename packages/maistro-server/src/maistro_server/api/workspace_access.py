"""Shared Workspace access checks for canonical Workspace-scoped APIs."""

from __future__ import annotations

from fastapi import HTTPException, status

from maistro.workspaces import WorkspaceMembership, WorkspaceNotFound, WorkspaceStore
from maistro_server.api.principal import AuthenticatedPrincipal

_workspace_store: WorkspaceStore | None = None


def configure_workspace_store(store: WorkspaceStore | None) -> None:
    """Install the canonical Workspace store served by Workspace-scoped routes."""
    global _workspace_store
    _workspace_store = store


def get_workspace_store() -> WorkspaceStore:
    if _workspace_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Workspace store is configured",
        )
    return _workspace_store


def user_id(auth: AuthenticatedPrincipal | None) -> str:
    """Return the authenticated user id, including the auth-disabled dev identity."""
    return auth.user_id if auth is not None else "dev"


async def require_workspace_membership(
    store: WorkspaceStore,
    workspace_id: str,
    requester_user_id: str,
) -> WorkspaceMembership:
    """Require membership without disclosing Workspace existence to outsiders."""
    try:
        membership = await store.get_membership(workspace_id, user_id=requester_user_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return membership


async def require_workspace_owner(
    store: WorkspaceStore,
    workspace_id: str,
    requester_user_id: str,
) -> WorkspaceMembership:
    """Require the canonical Workspace OWNER role."""
    membership = await require_workspace_membership(store, workspace_id, requester_user_id)
    if not membership.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace owner permission required",
        )
    return membership


__all__ = [
    "configure_workspace_store",
    "get_workspace_store",
    "require_workspace_membership",
    "require_workspace_owner",
    "user_id",
]
