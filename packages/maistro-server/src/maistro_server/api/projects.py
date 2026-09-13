"""Canonical Project tree API over the shared authorization boundary (#1150)."""

from __future__ import annotations

from typing import Annotated, Any, Self, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from maistro.projects.scope import (
    Project,
    ProjectIntegrityError,
    ProjectMembership,
    ProjectNotFound,
)
from maistro.projects.scope_store import ProjectScopeStore
from maistro.workspaces import WorkspaceProjectAccessDenied, WorkspaceProjectService
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import (
    access_http_error,
    get_project_service,
    principal,
)

router = APIRouter(prefix="/{workspace_id}/projects", tags=["projects"])


def get_project_scope_store(request: Request) -> ProjectScopeStore:
    """Compatibility accessor; product routes use the authorized service."""
    container = getattr(request.app.state, "container", None)
    store = getattr(container, "project_scope_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Project scope store is configured",
        )
    return cast(ProjectScopeStore, store)


class CreateProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_project_id: str = Field(min_length=1, pattern=r"\S")
    name: str = Field(min_length=1, pattern=r"\S")
    defaults: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MoveProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_project_id: str = Field(min_length=1, pattern=r"\S")


class UpdateProjectDefaultsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: dict[str, Any] = Field(default_factory=dict)


class AddProjectMembershipBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(min_length=1, pattern=r"\S")
    role: str | None = None
    grants: set[str] = Field(default_factory=set)
    denies: set[str] = Field(default_factory=set)
    delegable_grants: set[str] = Field(default_factory=set)

    @field_validator("grants", "denies", "delegable_grants")
    @classmethod
    def _require_non_blank_actions(cls, values: set[str]) -> set[str]:
        if any(not action.strip() for action in values):
            raise ValueError("permission actions must be non-empty strings")
        return values

    @model_validator(mode="after")
    def _delegation_requires_grant(self) -> Self:
        if not self.delegable_grants.issubset(self.grants):
            raise ValueError("delegable_grants must be a subset of grants")
        return self


@router.get("/root", response_model=Project)
async def get_root_project(
    workspace_id: str,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_project_service)],
) -> Project:
    try:
        return await service.get_root_project(principal(auth), workspace_id)
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc
    except ProjectNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


@router.get("/{project_id}", response_model=Project)
async def get_project(
    workspace_id: str,
    project_id: str,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_project_service)],
) -> Project:
    try:
        return await service.get_project(principal(auth), workspace_id, project_id)
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc


@router.get("/{project_id}/children", response_model=list[Project])
async def list_project_children(
    workspace_id: str,
    project_id: str,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_project_service)],
) -> list[Project]:
    try:
        return await service.list_project_children(principal(auth), workspace_id, project_id)
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    workspace_id: str,
    body: CreateProjectBody,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_project_service)],
) -> Project:
    try:
        return await service.create_project(
            principal(auth),
            workspace_id,
            parent_project_id=body.parent_project_id,
            name=body.name,
            defaults=body.defaults,
            metadata=body.metadata,
        )
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc
    except ProjectIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{project_id}/parent", response_model=Project)
async def move_project(
    workspace_id: str,
    project_id: str,
    body: MoveProjectBody,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_project_service)],
) -> Project:
    try:
        return await service.move_project(
            principal(auth),
            workspace_id,
            project_id,
            parent_project_id=body.parent_project_id,
        )
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc
    except (ProjectIntegrityError, ProjectNotFound) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/{project_id}/defaults", response_model=Project)
async def update_project_defaults(
    workspace_id: str,
    project_id: str,
    body: UpdateProjectDefaultsBody,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_project_service)],
) -> Project:
    try:
        return await service.update_project_defaults(
            principal(auth), workspace_id, project_id, defaults=body.defaults
        )
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    workspace_id: str,
    project_id: str,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_project_service)],
) -> None:
    try:
        await service.delete_project(principal(auth), workspace_id, project_id)
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc
    except (ProjectIntegrityError, ProjectNotFound) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{project_id}/memberships", response_model=list[ProjectMembership])
async def list_project_memberships(
    workspace_id: str,
    project_id: str,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_project_service)],
) -> list[ProjectMembership]:
    try:
        return await service.list_project_memberships(principal(auth), workspace_id, project_id)
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc


@router.post(
    "/{project_id}/memberships",
    response_model=ProjectMembership,
    status_code=status.HTTP_201_CREATED,
)
async def add_project_membership(
    workspace_id: str,
    project_id: str,
    body: AddProjectMembershipBody,
    auth: RequireAuth,
    service: Annotated[WorkspaceProjectService, Depends(get_project_service)],
) -> ProjectMembership:
    membership = ProjectMembership(
        workspace_id=workspace_id,
        project_id=project_id,
        principal_id=body.principal_id,
        role=body.role,
        grants=body.grants,
        denies=body.denies,
        delegable_grants=body.delegable_grants,
    )
    try:
        return await service.add_project_membership(
            principal(auth), workspace_id, project_id, membership
        )
    except WorkspaceProjectAccessDenied as exc:
        raise access_http_error(exc) from exc
    except ProjectIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


__all__ = ["get_project_scope_store", "router"]
