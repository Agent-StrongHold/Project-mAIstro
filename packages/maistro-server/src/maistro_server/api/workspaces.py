"""Canonical Workspace identity and membership API (#37).

All Workspace and Project operations cross the shared authorized service seam;
HTTP routes do not perform independent membership or role checks.
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
    WorkspaceProjectAccessDenied,
    WorkspaceProjectService,
    WorkspaceRole,
)
from maistro_server.api import projects
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import (
    access_http_error,
    configure_workspace_project_service,
    configure_workspace_store,
    get_workspace_project_service,
    get_workspace_store,
    principal,
    user_id,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
router.include_router(projects.router)

# Compatibility for callers/tests from the #37 slice. Store configuration now
# only supplies the low-level dependency used to construct the shared service.
_user_id = user_id


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
    service: Annotated[WorkspaceProjectService, Depends(get_workspace_project_service)],
) -> Workspace:
    return await service.create_workspace(
        principal(auth), name=body.name, description=body.description
    )


@router.get("", response_model=list[Workspace])
async def list_workspaces(
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_workspace_project_service)],
) -> list[Workspace]:
    return await service.list_workspaces(principal(auth))


@router.get("/{workspace_id}", response_model=Workspace)
async def get_workspace(
    workspace_id: str,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_workspace_project_service)],
) -> Workspace:
    try:
        return await service.get_workspace(principal(auth), workspace_id)
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc


@router.patch("/{workspace_id}", response_model=Workspace)
async def update_workspace(
    workspace_id: str,
    body: UpdateWorkspaceBody,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_workspace_project_service)],
) -> Workspace:
    try:
        return await service.update_workspace(
            principal(auth),
            workspace_id,
            name=body.name,
            description=body.description,
        )
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_workspace_project_service)],
) -> None:
    try:
        await service.delete_workspace(principal(auth), workspace_id)
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc
    except WorkspaceOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMembership])
async def list_members(
    workspace_id: str,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_workspace_project_service)],
) -> list[WorkspaceMembership]:
    try:
        return await service.list_workspace_members(principal(auth), workspace_id)
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc


@router.put("/{workspace_id}/members/{user_id}", response_model=WorkspaceMembership)
async def set_member(
    workspace_id: str,
    user_id: str,
    body: SetWorkspaceMembershipBody,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_workspace_project_service)],
) -> WorkspaceMembership:
    try:
        return await service.set_workspace_membership(
            principal(auth), workspace_id, user_id=user_id, role=body.role
        )
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc
    except WorkspaceAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    workspace_id: str,
    user_id: str,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_workspace_project_service)],
) -> None:
    try:
        await service.remove_workspace_membership(principal(auth), workspace_id, user_id=user_id)
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc
    except WorkspaceAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


__all__ = [
    "configure_workspace_project_service",
    "configure_workspace_store",
    "get_workspace_project_service",
    "get_workspace_store",
    "router",
]
