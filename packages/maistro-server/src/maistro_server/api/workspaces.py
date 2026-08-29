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
    WorkspaceNotFound,
    WorkspaceOwnershipError,
    WorkspaceRole,
    WorkspaceStore,
)
from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_workspace_store: WorkspaceStore | None = None


def configure_workspace_store(store: WorkspaceStore | None) -> None:
    """Install the canonical store served by these routes."""
    global _workspace_store
    _workspace_store = store


def get_workspace_store() -> WorkspaceStore:
    if _workspace_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Workspace store is configured",
        )
    return _workspace_store


def _user_id(auth: AuthenticatedPrincipal | None) -> str:
    return auth.user_id if auth is not None else "dev"


async def _require_membership(
    store: WorkspaceStore,
    workspace_id: str,
    user_id: str,
) -> WorkspaceMembership:
    try:
        membership = await store.get_membership(workspace_id, user_id=user_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    if membership is None:
        # Do not disclose that a Workspace exists to a non-member.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return membership


async def _require_owner(
    store: WorkspaceStore,
    workspace_id: str,
    user_id: str,
) -> WorkspaceMembership:
    membership = await _require_membership(store, workspace_id, user_id)
    if not membership.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace owner permission required",
        )
    return membership


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
    return await store.create(
        creator_user_id=_user_id(auth),
        name=body.name,
        description=body.description,
    )


@router.get("", response_model=list[Workspace])
async def list_workspaces(
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> list[Workspace]:
    return await store.list_for_user(_user_id(auth))


@router.get("/{workspace_id}", response_model=Workspace)
async def get_workspace(
    workspace_id: str,
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> Workspace:
    await _require_membership(store, workspace_id, _user_id(auth))
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
    await _require_owner(store, workspace_id, _user_id(auth))
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
    await _require_owner(store, workspace_id, _user_id(auth))
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
    await _require_membership(store, workspace_id, _user_id(auth))
    return await store.list_memberships(workspace_id)


@router.put("/{workspace_id}/members/{user_id}", response_model=WorkspaceMembership)
async def set_member(
    workspace_id: str,
    user_id: str,
    body: SetWorkspaceMembershipBody,
    auth: RequireAuth,
    store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
) -> WorkspaceMembership:
    await _require_owner(store, workspace_id, _user_id(auth))
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
    requester = _user_id(auth)
    requester_membership = await _require_membership(store, workspace_id, requester)
    if requester != user_id and not requester_membership.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace owner permission required",
        )
    try:
        await store.remove_membership(workspace_id, user_id=user_id)
    except WorkspaceAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
