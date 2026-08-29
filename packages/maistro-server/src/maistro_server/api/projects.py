"""Canonical Project tree and scoped-authorization API (#38).

The Project store owns structure and scope records. Workspace membership is the
outer access boundary: a caller must first belong to the Workspace, and only a
Workspace owner may mutate Project structure. Project-scoped delegation remains
granular: a non-owner may add a grant only when the canonical authorization
resolver says that exact action is delegable at the target Project.
"""

from __future__ import annotations

from typing import Annotated, Any, Self, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from maistro.projects.authorization import require_delegable_grant
from maistro.projects.scope import (
    Project,
    ProjectIntegrityError,
    ProjectMembership,
    ProjectNotFound,
)
from maistro.projects.scope_store import ProjectScopeStore
from maistro.workspaces import WorkspaceStore
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import (
    get_workspace_store,
    require_workspace_membership,
    require_workspace_owner,
    user_id,
)

router = APIRouter(prefix="/{workspace_id}/projects", tags=["projects"])


def get_project_scope_store(request: Request) -> ProjectScopeStore:
    """Return the exact Project store selected by the process Container."""
    container = getattr(request.app.state, "container", None)
    store = getattr(container, "project_scope_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Project scope store is configured",
        )
    return cast(ProjectScopeStore, store)


async def _require_project(
    store: ProjectScopeStore,
    *,
    workspace_id: str,
    project_id: str,
) -> Project:
    project = await store.get(project_id)
    if project is None or project.workspace_id != workspace_id:
        # Do not disclose cross-Workspace Project identifiers.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


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
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    project_store: Annotated[ProjectScopeStore, Depends(get_project_scope_store)],
) -> Project:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    try:
        return await project_store.root_for_workspace(workspace_id)
    except ProjectNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from exc


@router.get("/{project_id}", response_model=Project)
async def get_project(
    workspace_id: str,
    project_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    project_store: Annotated[ProjectScopeStore, Depends(get_project_scope_store)],
) -> Project:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    return await _require_project(
        project_store,
        workspace_id=workspace_id,
        project_id=project_id,
    )


@router.get("/{project_id}/children", response_model=list[Project])
async def list_project_children(
    workspace_id: str,
    project_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    project_store: Annotated[ProjectScopeStore, Depends(get_project_scope_store)],
) -> list[Project]:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    await _require_project(project_store, workspace_id=workspace_id, project_id=project_id)
    return await project_store.list_children(project_id)


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    workspace_id: str,
    body: CreateProjectBody,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    project_store: Annotated[ProjectScopeStore, Depends(get_project_scope_store)],
) -> Project:
    await require_workspace_owner(workspace_store, workspace_id, user_id(auth))
    await _require_project(
        project_store,
        workspace_id=workspace_id,
        project_id=body.parent_project_id,
    )
    try:
        return await project_store.create(
            workspace_id=workspace_id,
            parent_project_id=body.parent_project_id,
            name=body.name,
            defaults=body.defaults,
            metadata=body.metadata,
        )
    except ProjectIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{project_id}/parent", response_model=Project)
async def move_project(
    workspace_id: str,
    project_id: str,
    body: MoveProjectBody,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    project_store: Annotated[ProjectScopeStore, Depends(get_project_scope_store)],
) -> Project:
    await require_workspace_owner(workspace_store, workspace_id, user_id(auth))
    await _require_project(project_store, workspace_id=workspace_id, project_id=project_id)
    await _require_project(
        project_store,
        workspace_id=workspace_id,
        project_id=body.parent_project_id,
    )
    try:
        return await project_store.move_project(
            project_id,
            parent_project_id=body.parent_project_id,
        )
    except (ProjectIntegrityError, ProjectNotFound) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/{project_id}/defaults", response_model=Project)
async def update_project_defaults(
    workspace_id: str,
    project_id: str,
    body: UpdateProjectDefaultsBody,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    project_store: Annotated[ProjectScopeStore, Depends(get_project_scope_store)],
) -> Project:
    await require_workspace_owner(workspace_store, workspace_id, user_id(auth))
    await _require_project(project_store, workspace_id=workspace_id, project_id=project_id)
    return await project_store.update_defaults(project_id, defaults=body.defaults)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    workspace_id: str,
    project_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    project_store: Annotated[ProjectScopeStore, Depends(get_project_scope_store)],
) -> None:
    await require_workspace_owner(workspace_store, workspace_id, user_id(auth))
    await _require_project(project_store, workspace_id=workspace_id, project_id=project_id)
    try:
        await project_store.delete(project_id)
    except (ProjectIntegrityError, ProjectNotFound) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{project_id}/memberships", response_model=list[ProjectMembership])
async def list_project_memberships(
    workspace_id: str,
    project_id: str,
    auth: RequireAuth,
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    project_store: Annotated[ProjectScopeStore, Depends(get_project_scope_store)],
) -> list[ProjectMembership]:
    await require_workspace_owner(workspace_store, workspace_id, user_id(auth))
    await _require_project(project_store, workspace_id=workspace_id, project_id=project_id)
    return await project_store.memberships_for(project_id)


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
    workspace_store: Annotated[WorkspaceStore, Depends(get_workspace_store)],
    project_store: Annotated[ProjectScopeStore, Depends(get_project_scope_store)],
) -> ProjectMembership:
    requester = user_id(auth)
    requester_membership = await require_workspace_membership(
        workspace_store,
        workspace_id,
        requester,
    )
    await _require_project(project_store, workspace_id=workspace_id, project_id=project_id)

    if not requester_membership.can_administer:
        if body.denies:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace owner permission required to issue Project denies",
            )
        # Holding an action is not enough to grant it. Every action this record
        # would confer must already be explicitly delegable at this scope.
        for action in sorted(body.grants):
            try:
                await require_delegable_grant(
                    project_store,
                    project_id=project_id,
                    principal_id=requester,
                    action=action,
                )
            except PermissionError as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

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
        return await project_store.set_membership(membership)
    except ProjectIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


__all__ = ["get_project_scope_store", "router"]
