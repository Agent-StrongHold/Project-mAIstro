"""Workspace BacklogItem API (#98).

Workspace membership is the boundary: any member reads, only a CONTRIBUTOR or
OWNER writes, and an outsider -- or an id from another Workspace -- gets 404 so
the route never discloses what exists elsewhere. Field edits are a
compare-and-set on `expected_version`; a stale one gets 409 with the item as it
now stands, so the UI or agent can rebase instead of overwriting.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any, Self

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro.workspaces import WorkspaceStore
from maistro.workspaces.backlog import (
    BacklogItem,
    BacklogItemAlreadyExists,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogItemStore,
    BacklogRelationError,
    BacklogVersionConflict,
    GoalReference,
)
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import (
    get_workspace_store,
    require_workspace_membership,
    user_id,
)

router = APIRouter(prefix="/{workspace_id}/backlog", tags=["backlog"])


class _Conflict(Exception):
    def __init__(self, current: BacklogItem) -> None:
        self.current = current


def get_backlog_store(request: Request) -> BacklogItemStore:
    """The BacklogItem store the process Container selected."""
    try:
        store: BacklogItemStore | None = request.app.state.container.backlog_store
    except AttributeError:
        store = None
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No BacklogItem store is configured",
        )
    return store


class _ItemFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_key: str | None = None
    description: str = ""
    status: BacklogItemStatus = BacklogItemStatus.PROPOSED
    priority: str | None = None
    risk: str | None = None
    source: str | None = None
    owner_principal_id: str | None = None
    milestone: str | None = None
    acceptance_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    spec_refs: list[str] = Field(default_factory=list)
    scenario_refs: list[str] = Field(default_factory=list)
    allowed_scope: list[str] = Field(default_factory=list)
    protected_scope: list[str] = Field(default_factory=list)
    autonomy_mode: str | None = None
    rank: float = 0.0
    paused: bool = False
    pinned: bool = False
    goal_ref: GoalReference | None = None


class CreateBacklogItemBody(_ItemFields):
    project_id: str = Field(min_length=1, pattern=r"\S")
    title: str = Field(min_length=1, pattern=r"\S")
    parent_item_id: str | None = None


#: The BacklogItem fields an update may clear by sending ``null``.
_NULLABLE_FIELDS = frozenset(
    {
        "external_key",
        "priority",
        "risk",
        "source",
        "owner_principal_id",
        "milestone",
        "autonomy_mode",
        "archived_at",
        "goal_ref",
    }
)


class UpdateBacklogItemBody(BaseModel):
    """Only the fields sent are changed; `expected_version` is mandatory."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    project_id: str | None = Field(default=None, min_length=1, pattern=r"\S")
    title: str | None = Field(default=None, min_length=1, pattern=r"\S")
    external_key: str | None = None
    description: str | None = None
    status: BacklogItemStatus | None = None
    priority: str | None = None
    risk: str | None = None
    source: str | None = None
    owner_principal_id: str | None = None
    milestone: str | None = None
    acceptance_refs: list[str] | None = None
    evidence_refs: list[str] | None = None
    spec_refs: list[str] | None = None
    scenario_refs: list[str] | None = None
    allowed_scope: list[str] | None = None
    protected_scope: list[str] | None = None
    autonomy_mode: str | None = None
    rank: float | None = None
    paused: bool | None = None
    pinned: bool | None = None
    archived_at: datetime | None = None
    goal_ref: GoalReference | None = None

    @model_validator(mode="after")
    def _no_null_for_required_fields(self) -> Self:
        nulled = sorted(
            name
            for name in self.model_fields_set
            if getattr(self, name) is None and name not in _NULLABLE_FIELDS
        )
        if nulled:
            raise ValueError(f"{', '.join(nulled)} cannot be null")
        return self


class SetParentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    parent_item_id: str | None


@contextmanager
def _store_errors() -> Iterator[None]:
    """Translate the store's refusals into the route's status codes."""
    try:
        yield
    except BacklogVersionConflict as exc:
        raise _Conflict(exc.current_item) from exc
    except BacklogItemNotFound as exc:
        raise _not_found() from exc
    except BacklogRelationError as exc:
        if exc.kind == "cross_workspace":
            raise _not_found() from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except BacklogItemAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="BacklogItem already exists"
        ) from exc
    except ValueError as exc:
        # Checked by BacklogItem rather than the request body: FastAPI's own
        # 422 echoes the input, and a non-finite rank cannot be encoded.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="BacklogItem field values are invalid",
        ) from exc


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BacklogItem not found")


def _conflict_response(conflict: _Conflict) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": "BacklogItem version conflict",
            "current": conflict.current.model_dump(mode="json"),
        },
    )


async def _require_reader(workspace_store: WorkspaceStore, workspace_id: str, auth: Any) -> None:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))


async def _require_contributor(
    workspace_store: WorkspaceStore, workspace_id: str, auth: Any
) -> None:
    membership = await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    if not membership.can_contribute:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace contributor permission required",
        )


async def _require_item(store: BacklogItemStore, workspace_id: str, item_id: str) -> BacklogItem:
    item = await store.get(item_id)
    if item is None or item.workspace_id != workspace_id:
        raise _not_found()
    return item


WorkspaceStoreDep = Annotated[WorkspaceStore, Depends(get_workspace_store)]
BacklogStoreDep = Annotated[BacklogItemStore, Depends(get_backlog_store)]


@router.get("", response_model=list[BacklogItem])
async def list_backlog_items(
    workspace_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
    project_id: Annotated[str | None, Query()] = None,
    item_status: Annotated[BacklogItemStatus | None, Query(alias="status")] = None,
) -> list[BacklogItem]:
    await _require_reader(workspace_store, workspace_id, auth)
    return await store.list(workspace_id, project_id=project_id, status=item_status)


@router.post("", response_model=BacklogItem, status_code=status.HTTP_201_CREATED)
async def create_backlog_item(
    workspace_id: str,
    body: CreateBacklogItemBody,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogItem:
    await _require_contributor(workspace_store, workspace_id, auth)
    with _store_errors():
        item = BacklogItem(workspace_id=workspace_id, **body.model_dump())
        return await store.create(item)


@router.get("/{item_id}", response_model=BacklogItem)
async def get_backlog_item(
    workspace_id: str,
    item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogItem:
    await _require_reader(workspace_store, workspace_id, auth)
    return await _require_item(store, workspace_id, item_id)


@router.patch(
    "/{item_id}",
    response_model=BacklogItem,
    responses={status.HTTP_409_CONFLICT: {"description": "Stale expected_version"}},
)
async def update_backlog_item(
    workspace_id: str,
    item_id: str,
    body: UpdateBacklogItemBody,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogItem | JSONResponse:
    await _require_contributor(workspace_store, workspace_id, auth)
    await _require_item(store, workspace_id, item_id)
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    try:
        with _store_errors():
            return await store.update(
                item_id, expected_version=body.expected_version, changes=changes
            )
    except _Conflict as conflict:
        return _conflict_response(conflict)


@router.put(
    "/{item_id}/parent",
    response_model=BacklogItem,
    responses={status.HTTP_409_CONFLICT: {"description": "Stale version or cycle"}},
)
async def set_backlog_item_parent(
    workspace_id: str,
    item_id: str,
    body: SetParentBody,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogItem | JSONResponse:
    await _require_contributor(workspace_store, workspace_id, auth)
    await _require_item(store, workspace_id, item_id)
    if body.parent_item_id is not None:
        await _require_item(store, workspace_id, body.parent_item_id)
    try:
        with _store_errors():
            return await store.set_parent(
                item_id, body.parent_item_id, expected_version=body.expected_version
            )
    except _Conflict as conflict:
        return _conflict_response(conflict)


@router.get("/{item_id}/children", response_model=list[BacklogItem])
async def list_backlog_item_children(
    workspace_id: str,
    item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> list[BacklogItem]:
    await _require_reader(workspace_store, workspace_id, auth)
    await _require_item(store, workspace_id, item_id)
    return await store.children_of(item_id)


@router.get("/{item_id}/dependencies", response_model=list[BacklogItem])
async def list_backlog_item_dependencies(
    workspace_id: str,
    item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> list[BacklogItem]:
    await _require_reader(workspace_store, workspace_id, auth)
    await _require_item(store, workspace_id, item_id)
    return await store.dependencies_of(item_id)


@router.get("/{item_id}/dependents", response_model=list[BacklogItem])
async def list_backlog_item_dependents(
    workspace_id: str,
    item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> list[BacklogItem]:
    await _require_reader(workspace_store, workspace_id, auth)
    await _require_item(store, workspace_id, item_id)
    return await store.dependents_of(item_id)


@router.put("/{item_id}/dependencies/{depends_on_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_backlog_item_dependency(
    workspace_id: str,
    item_id: str,
    depends_on_item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> None:
    await _require_contributor(workspace_store, workspace_id, auth)
    await _require_item(store, workspace_id, item_id)
    await _require_item(store, workspace_id, depends_on_item_id)
    with _store_errors():
        await store.add_dependency(item_id, depends_on_item_id)


@router.delete(
    "/{item_id}/dependencies/{depends_on_item_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_backlog_item_dependency(
    workspace_id: str,
    item_id: str,
    depends_on_item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> None:
    await _require_contributor(workspace_store, workspace_id, auth)
    await _require_item(store, workspace_id, item_id)
    with _store_errors():
        await store.remove_dependency(item_id, depends_on_item_id)


__all__ = ["get_backlog_store", "router"]
