"""Workspace BacklogItem work-source API (#98).

The HTTP surface over the one canonical BacklogItem store
(``maistro.backlog``): create, inspect, edit, close, reopen, and claim
Workspace work items. A claim is a lease on the right to progress an item
now — it coordinates actors and never reassigns Goal ownership — and every
content edit names the ``expected_version`` it read, so two concurrent
editors get an explicit 409 rather than a silent merge.

Authorization is fail closed, exactly like the history surface (#101): only
Workspace members reach any route here, an outsider gets the same 404 an
unknown Workspace gets, and an item filed in another Workspace is answered
with 404 so the store is not an existence oracle for foreign work.
"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from maistro.backlog.model import (
    BacklogClaim,
    BacklogClaimError,
    BacklogClosureError,
    BacklogEvent,
    BacklogItem,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogVersionConflict,
)
from maistro.backlog.store import DEFAULT_LEASE_SECONDS, UNSET, BacklogStore
from maistro.workspaces import WorkspaceStore
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import (
    get_workspace_store,
    require_workspace_membership,
    user_id,
)

router = APIRouter(prefix="/{workspace_id}/backlog-items", tags=["backlog-items"])


def get_backlog_store(request: Request) -> BacklogStore:
    """The BacklogItem work-source store the process Container selected."""
    try:
        store: BacklogStore | None = request.app.state.container.backlog_store
    except AttributeError:
        store = None
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No BacklogItem work-source store is configured",
        )
    return store


BacklogStoreDep = Annotated[BacklogStore, Depends(get_backlog_store)]
WorkspaceStoreDep = Annotated[WorkspaceStore, Depends(get_workspace_store)]


async def _authorized_item(
    workspace_id: str,
    item_id: str,
    *,
    workspace_store: WorkspaceStore,
    auth: RequireAuth,
    store: BacklogStore,
) -> BacklogItem:
    """One item of this Workspace, or the 404 that hides every other answer."""
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    item = await store.get_item(item_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BacklogItem not found",
        )
    return item


def _raise_not_found(exc: BacklogItemNotFound) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="BacklogItem not found",
    ) from exc


class CreateBacklogItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    details: str = ""
    tags: tuple[str, ...] = ()
    milestone: str | None = None
    package: str | None = None
    risk_notes: str = ""
    parent_id: str | None = None
    goal_id: str | None = None
    goal_revision: int | None = Field(default=None, ge=1)
    source: str = "human"


class UpdateBacklogItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1)
    details: str | None = None
    risk_notes: str | None = None
    tags: tuple[str, ...] | None = None
    milestone: str | None = None
    package: str | None = None
    parent_id: str | None = None
    goal_id: str | None = None
    goal_revision: int | None = Field(default=None, ge=1)
    status: BacklogItemStatus | None = None


class CloseBacklogItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    outcome: BacklogItemStatus
    closure_summary: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class ClaimBacklogItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_seconds: float = Field(default=DEFAULT_LEASE_SECONDS, gt=0)


class ExtendClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    lease_seconds: float = Field(gt=0)


class ReleaseClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)


class ReopenBacklogItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


@router.get("", response_model=list[BacklogItem])
async def list_backlog_items(
    workspace_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
    item_status: Annotated[BacklogItemStatus | None, Query(alias="status")] = None,
    tag: Annotated[str | None, Query()] = None,
    parent_id: Annotated[str | None, Query()] = None,
    roots_only: Annotated[bool, Query()] = False,
) -> list[BacklogItem]:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    return await store.list_items(
        workspace_id,
        status=item_status,
        tag=tag,
        parent_id=parent_id,
        roots_only=roots_only,
    )


@router.post("", response_model=BacklogItem, status_code=status.HTTP_201_CREATED)
async def create_backlog_item(
    workspace_id: str,
    body: CreateBacklogItemBody,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogItem:
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    try:
        return await store.create_item(
            workspace_id=workspace_id,
            title=body.title,
            details=body.details,
            tags=body.tags,
            milestone=body.milestone,
            package=body.package,
            risk_notes=body.risk_notes,
            parent_id=body.parent_id,
            goal_id=body.goal_id,
            goal_revision=body.goal_revision,
            source=body.source,
            actor=user_id(auth),
        )
    except BacklogItemNotFound as exc:
        # A parent_id naming an item of another Workspace is answered with the
        # same 404 as an unknown parent: no existence oracle.
        _raise_not_found(exc)


@router.get("/{item_id}", response_model=BacklogItem)
async def get_backlog_item(
    workspace_id: str,
    item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogItem:
    return await _authorized_item(
        workspace_id, item_id, workspace_store=workspace_store, auth=auth, store=store
    )


@router.patch("/{item_id}", response_model=BacklogItem)
async def update_backlog_item(
    workspace_id: str,
    item_id: str,
    body: UpdateBacklogItemBody,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogItem:
    await _authorized_item(
        workspace_id, item_id, workspace_store=workspace_store, auth=auth, store=store
    )
    # JSON cannot say "no opinion" versus "clear", but the store's tri-state
    # can: a field absent from the request body is UNSET (leave unchanged),
    # while an explicit null clears. `model_fields_set` is that distinction.
    provided = body.model_fields_set
    try:
        return await store.update_item(
            item_id,
            expected_version=body.expected_version,
            actor=user_id(auth),
            title=body.title,
            details=body.details,
            risk_notes=body.risk_notes,
            tags=body.tags,
            milestone=body.milestone if "milestone" in provided else UNSET,
            package=body.package if "package" in provided else UNSET,
            parent_id=body.parent_id if "parent_id" in provided else UNSET,
            goal_id=body.goal_id if "goal_id" in provided else UNSET,
            goal_revision=body.goal_revision if "goal_revision" in provided else UNSET,
            status=body.status,
        )
    except BacklogItemNotFound as exc:
        _raise_not_found(exc)
    except BacklogVersionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "BacklogItem was changed concurrently",
                "current_version": exc.current_version,
            },
        ) from exc
    except ValueError as exc:
        # The store refuses terminal-status edits through update_item: closure
        # evidence must go through close_item, which is a recorded decision.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post("/{item_id}/close", response_model=BacklogItem)
async def close_backlog_item(
    workspace_id: str,
    item_id: str,
    body: CloseBacklogItemBody,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogItem:
    await _authorized_item(
        workspace_id, item_id, workspace_store=workspace_store, auth=auth, store=store
    )
    try:
        return await store.close_item(
            item_id,
            expected_version=body.expected_version,
            actor=user_id(auth),
            outcome=body.outcome,
            closure_summary=body.closure_summary,
            evidence_refs=body.evidence_refs,
        )
    except BacklogItemNotFound as exc:
        _raise_not_found(exc)
    except BacklogClosureError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except BacklogVersionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "BacklogItem was changed concurrently",
                "current_version": exc.current_version,
            },
        ) from exc


@router.post("/{item_id}/reopen", response_model=BacklogItem)
async def reopen_backlog_item(
    workspace_id: str,
    item_id: str,
    body: ReopenBacklogItemBody,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogItem:
    await _authorized_item(
        workspace_id, item_id, workspace_store=workspace_store, auth=auth, store=store
    )
    try:
        return await store.reopen_item(
            item_id,
            expected_version=body.expected_version,
            actor=user_id(auth),
        )
    except BacklogItemNotFound as exc:
        _raise_not_found(exc)
    except BacklogClosureError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except BacklogVersionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "BacklogItem was changed concurrently",
                "current_version": exc.current_version,
            },
        ) from exc


@router.post("/{item_id}/claim", response_model=BacklogClaim)
async def claim_backlog_item(
    workspace_id: str,
    item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
    body: ClaimBacklogItemBody | None = None,
) -> BacklogClaim:
    await _authorized_item(
        workspace_id, item_id, workspace_store=workspace_store, auth=auth, store=store
    )
    lease = body.lease_seconds if body is not None else DEFAULT_LEASE_SECONDS
    try:
        return await store.claim_item(
            item_id,
            claimed_by=user_id(auth),
            lease_seconds=lease,
        )
    except BacklogItemNotFound as exc:
        _raise_not_found(exc)
    except BacklogClaimError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "BacklogItem is already claimed", "claim_id": exc.claim.claim_id},
        ) from exc


@router.post("/{item_id}/claims/extend", response_model=BacklogClaim)
async def extend_backlog_claim(
    workspace_id: str,
    item_id: str,
    body: ExtendClaimBody,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> BacklogClaim:
    await _authorized_item(
        workspace_id, item_id, workspace_store=workspace_store, auth=auth, store=store
    )
    try:
        return await store.extend_claim(
            item_id,
            claim_id=body.claim_id,
            lease_seconds=body.lease_seconds,
            actor=user_id(auth),
        )
    except BacklogItemNotFound as exc:
        _raise_not_found(exc)
    except BacklogClaimError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "No live claim under that id", "claim_id": body.claim_id},
        ) from exc


@router.post("/{item_id}/claims/release", status_code=status.HTTP_204_NO_CONTENT)
async def release_backlog_claim(
    workspace_id: str,
    item_id: str,
    body: ReleaseClaimBody,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> None:
    await _authorized_item(
        workspace_id, item_id, workspace_store=workspace_store, auth=auth, store=store
    )
    try:
        await store.release_claim(
            item_id,
            claim_id=body.claim_id,
            actor=user_id(auth),
        )
    except BacklogItemNotFound as exc:
        _raise_not_found(exc)
    except BacklogClaimError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "No live claim under that id", "claim_id": body.claim_id},
        ) from exc


@router.get("/{item_id}/events", response_model=list[BacklogEvent])
async def list_backlog_item_events(
    workspace_id: str,
    item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogStoreDep,
) -> list[BacklogEvent]:
    await _authorized_item(
        workspace_id, item_id, workspace_store=workspace_store, auth=auth, store=store
    )
    return await store.events(item_id)


__all__ = [
    "ClaimBacklogItemBody",
    "CloseBacklogItemBody",
    "CreateBacklogItemBody",
    "ExtendClaimBody",
    "ReleaseClaimBody",
    "ReopenBacklogItemBody",
    "UpdateBacklogItemBody",
    "claim_backlog_item",
    "close_backlog_item",
    "create_backlog_item",
    "extend_backlog_claim",
    "get_backlog_item",
    "get_backlog_store",
    "list_backlog_item_events",
    "list_backlog_items",
    "release_backlog_claim",
    "reopen_backlog_item",
    "router",
    "update_backlog_item",
]
