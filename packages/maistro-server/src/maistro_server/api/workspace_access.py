"""Shared Workspace access checks for canonical Workspace-scoped APIs."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar

from fastapi import HTTPException, status

from maistro.workspaces import (
    WorkspaceAction,
    WorkspaceAuthorizationDenied,
    WorkspaceAuthorizer,
    WorkspaceMembership,
    WorkspaceStore,
)
from maistro_server.api.principal import AuthenticatedPrincipal

_T = TypeVar("_T")

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


def workspace_denial(exc: WorkspaceAuthorizationDenied) -> HTTPException:
    """Render a Workspace authorization refusal as the route's own answer.

    The canonical store re-resolves the acting principal's authority inside
    the store call (#1150), so a revocation that lands between a route's own
    check and the store call arrives here as a refusal. A principal who is
    still a member but lost the action gets the route's 403; a principal who
    is no longer a member gets the same 404 an unknown Workspace gets. The
    refusal never escapes as a 500 and never becomes an existence oracle.
    """
    if exc.membership is not None:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace owner permission required",
        )
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Workspace not found",
    )


async def authorized(coro: Awaitable[_T]) -> _T:
    """Await a canonical store call and render its refusal as the route's answer.

    The store boundary is the authority (#1150); this is only the translation
    of its refusal into the answer the route already gives for the same
    situation.
    """
    try:
        return await coro
    except WorkspaceAuthorizationDenied as exc:
        raise workspace_denial(exc) from exc


async def _require(
    store: WorkspaceStore,
    workspace_id: str,
    requester_user_id: str,
    action: WorkspaceAction,
) -> WorkspaceMembership:
    try:
        return await WorkspaceAuthorizer(store).require(requester_user_id, workspace_id, action)
    except WorkspaceAuthorizationDenied as exc:
        raise workspace_denial(exc) from exc


async def require_workspace_membership(
    store: WorkspaceStore,
    workspace_id: str,
    requester_user_id: str,
) -> WorkspaceMembership:
    """Require membership without disclosing Workspace existence to outsiders."""
    return await _require(store, workspace_id, requester_user_id, WorkspaceAction.VIEW)


async def require_workspace_owner(
    store: WorkspaceStore,
    workspace_id: str,
    requester_user_id: str,
) -> WorkspaceMembership:
    """Require the canonical Workspace OWNER role."""
    return await _require(store, workspace_id, requester_user_id, WorkspaceAction.ADMINISTER)


__all__ = [
    "authorized",
    "configure_workspace_store",
    "get_workspace_store",
    "require_workspace_membership",
    "require_workspace_owner",
    "user_id",
    "workspace_denial",
]
