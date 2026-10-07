"""Canonical Workspace identity and membership API (#37).

This is an ownership boundary, not a second Workspace model. Product-specific
persona/tab state belongs in a projection keyed by ``workspace_id``; access
stays in separate ``WorkspaceMembership`` records owned by ``WorkspaceStore``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from maistro.workspaces import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceMembership,
    WorkspaceOwnershipError,
    WorkspaceRole,
    WorkspaceStore,
)
from maistro_server.api import backlog_history, backlog_items, campaigns, projects
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import (
    configure_workspace_store,
    get_workspace_store,
    require_workspace_membership,
    require_workspace_owner,
)
from maistro_server.api.workspace_access import (
    user_id as authenticated_user_id,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
router.include_router(projects.router)
router.include_router(backlog_history.router)
# The canonical BacklogItem work-source (#98): create/edit/close and
# claim/lease over the one `maistro.backlog` store the Container selected.
# Included here because an item is scoped to the Workspace it files under, so
# its routes share this prefix and its membership boundary.
router.include_router(backlog_items.router)
# Workspace work campaigns (#103): operator controls under
# /{workspace_id}/campaigns. Included here because a campaign is scoped to
# the Workspace its operators steer, so its routes share this prefix and its
# authorization boundary.
router.include_router(campaigns.router)

# Compatibility for callers/tests from the #37 slice. The implementation now
# lives in workspace_access so Project and Workspace routes share one boundary.
_user_id = authenticated_user_id
_require_membership = require_workspace_membership
_require_owner = require_workspace_owner


class CreateWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"\S")
    description: str = ""


class UpdateWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, pattern=r"\S")
    description: str | None = None


class SetWorkspaceMembershipBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: WorkspaceRole


@router.post("", response_model=Workspace, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: CreateWorkspaceBody,
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> Workspace:
    """Create a Workspace owned by the authenticated caller.

    The creator becomes its owner in the same call: a Workspace with no owner
    could never be administered, so ownership is not a separate step that can
    fail on its own.
    """
    return await store.create(
        creator_user_id=authenticated_user_id(auth),
        name=body.name,
        description=body.description,
    )


@router.get("", response_model=list[Workspace])
async def list_workspaces(
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> list[Workspace]:
    """List the Workspaces the caller is a member of.

    Scoped to the caller rather than filtered after the fact: membership is the
    read boundary, so a Workspace the caller cannot see is never fetched.
    """
    return await store.list_for_user(authenticated_user_id(auth))


@router.get("/{workspace_id}", response_model=Workspace)
async def get_workspace(
    workspace_id: str,
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> Workspace:
    """Return one Workspace, for any member of it.

    Membership is checked before the fetch, so a non-member gets the access
    error rather than a 404 that would confirm the Workspace exists.
    """
    await require_workspace_membership(store, workspace_id, authenticated_user_id(auth))
    workspace = await store.get(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


@router.patch("/{workspace_id}", response_model=Workspace)
async def update_workspace(
    workspace_id: str,
    body: UpdateWorkspaceBody,
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> Workspace:
    """Update a Workspace's name or description. Owner only.

    Absent fields are left alone rather than cleared, so a caller sending one
    field does not blank the other.
    """
    await require_workspace_owner(store, workspace_id, authenticated_user_id(auth))
    workspace = await store.get(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    updates: dict[str, object] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    return await store.update(workspace.model_copy(update=updates))


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str,
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> None:
    """Delete a Workspace. Owner only.

    Refuses with 409 when the store reports the Workspace still owns something
    that would be orphaned by removing it.
    """
    await require_workspace_owner(store, workspace_id, authenticated_user_id(auth))
    try:
        await store.delete(workspace_id)
    except WorkspaceOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMembership])
async def list_members(
    workspace_id: str,
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> list[WorkspaceMembership]:
    """List a Workspace's memberships, for any member of it.

    Members can see who else belongs; changing membership is owner-only.
    """
    await require_workspace_membership(store, workspace_id, authenticated_user_id(auth))
    return await store.list_memberships(workspace_id)


@router.put("/{workspace_id}/members/{user_id}", response_model=WorkspaceMembership)
async def set_member(
    workspace_id: str,
    user_id: str,
    body: SetWorkspaceMembershipBody,
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> WorkspaceMembership:
    """Add a member or change their role. Owner only.

    Idempotent on the pair: setting an existing member's current role is not an
    error. 409 when the store refuses the change -- removing the last owner
    through a role downgrade is the case that matters.
    """
    await require_workspace_owner(store, workspace_id, authenticated_user_id(auth))
    try:
        return await store.set_membership(workspace_id, user_id=user_id, role=body.role)
    except WorkspaceAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    workspace_id: str,
    user_id: str,
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> None:
    """Remove a member. Owner only, except that anyone may remove themselves.

    The self-removal exception is deliberate: leaving a Workspace should not
    require the permission to administer it. 409 when the store refuses --
    the last owner cannot leave, because that would strand the Workspace.
    """
    requester = authenticated_user_id(auth)
    requester_membership = await require_workspace_membership(store, workspace_id, requester)
    if requester != user_id and not requester_membership.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace owner permission required",
        )
    try:
        await store.remove_membership(workspace_id, user_id=user_id)
    except WorkspaceAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


__all__ = ["configure_workspace_store", "get_workspace_store", "router"]
