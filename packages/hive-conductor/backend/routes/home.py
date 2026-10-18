"""Workspace Home routes (#1048) — layout authority, projections, adaptive composition.

Home is a composition layer over canonical services, so this router is a thin
adapter over two services:

- `services.home_layouts` — the durable, revision-checked, workspace-scoped
  layout, with the user/Agent authority split (the Agent composes only
  unpinned space, `compose_adaptive` refuses everything else);
- `services.home_projections` — read-time compact projections over the same
  canonical services every other surface reads, plus backend-recorded
  adaptive dismissals.

Authorization is the Workspace's own, fail closed: a caller who is not a
member gets the same 404 a missing Workspace gets (no existence oracle), a
viewer member gets 403 on every write, and every write is a service call —
there is no second write path for the Agent tool to bypass.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from services import home_layouts, home_projections
from services.home_layouts import (
    HomeLayout,
    LayoutConflictError,
    LayoutError,
    LayoutPersistenceError,
    PinnedRegionWriteError,
)
from services.request_principal import require_actor_id
from services.workspace_authority import member_role, visible_view

router = APIRouter(tags=["home"])
logger = logging.getLogger("hive.home")


async def _require_member(request: Request, workspace_id: str) -> str:
    """The actor, after a membership check that cannot be skipped.

    Not a member and not a Workspace look identical from the outside: both are
    404, so the route is not an existence oracle for other people's Workspaces.
    """
    user_id = require_actor_id(request)
    if await visible_view(user_id, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return user_id


async def _require_writer(request: Request, workspace_id: str) -> str:
    user_id = await _require_member(request, workspace_id)
    if await member_role(user_id, workspace_id) == "viewer":
        raise HTTPException(
            status_code=403, detail="read-only Workspace members cannot change Home"
        )
    return user_id


class HomeRegionBody(BaseModel):
    """One region on the wire. Mirrors `services.home_layouts.HomeRegion`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    pinned: bool = False
    resource_type: str = "none"
    resource_id: str | None = None
    position: int = 0
    size: str = "1"
    reason: str | None = None


class HomeLayoutBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regions: list[HomeRegionBody] = Field(default_factory=list)
    expectedRevision: int | None = None


class AdaptiveComposeBody(BaseModel):
    """The Agent's composition of the unpinned space. No `pinned` field: the
    Agent cannot pin, so the wire shape does not offer it."""

    model_config = ConfigDict(extra="forbid")

    regions: list[HomeRegionBody] = Field(default_factory=list)
    expectedRevision: int | None = None


class RegionPinBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pinned: bool
    expectedRevision: int | None = None


class AdaptiveDismissBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itemType: str = Field(min_length=1, max_length=64)
    itemId: str = Field(min_length=1, max_length=256)


def _layout_dict(record: home_layouts.HomeLayoutRecord) -> dict[str, Any]:
    return {
        "revision": record.revision,
        "updatedAt": record.updated_at.isoformat(),
        "regions": [r.model_dump(mode="json") for r in record.layout.regions],
    }


def _regions_from(body_items: list[HomeRegionBody]) -> list[home_layouts.HomeRegion]:
    return [home_layouts.HomeRegion.model_validate(r.model_dump()) for r in body_items]


def _refuse(exc: Exception, what: str) -> HTTPException:
    """The failures with an answer of their own, named; nothing swallowed."""
    if isinstance(exc, LayoutConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "message": f"{what} changed since you loaded it",
                "revision": exc.stored.revision,
                "regions": [r.model_dump(mode="json") for r in exc.stored.layout.regions],
            },
        )
    if isinstance(exc, PinnedRegionWriteError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LayoutPersistenceError):
        logger.error("home %s was not persisted: %s", what, exc)
        return HTTPException(status_code=503, detail=f"the {what} was not saved: {exc}")
    if isinstance(exc, LayoutError):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


@router.get("/{workspace_id}/home/layout")
async def get_home_layout(workspace_id: str, request: Request) -> dict[str, Any]:
    """The Workspace's stored Home layout, or the default composition.

    `effective` rather than `load`: a Workspace that never saved is offered the
    default (nothing pinned — the Agent may compose all of it) without being
    persisted on a read, exactly like the dashboard's preset.
    """
    await _require_member(request, workspace_id)
    return _layout_dict(home_layouts.effective(workspace_id))


@router.put("/{workspace_id}/home/layout")
async def save_home_layout(
    workspace_id: str, body: HomeLayoutBody, request: Request
) -> dict[str, Any]:
    """Store the user's full Home layout, or say it was not stored.

    Only the failures with an answer of their own are caught, and each names
    what it is — the same discipline `PUT /v1/dashboard/layout` holds.
    """
    await _require_writer(request, workspace_id)
    layout = HomeLayout(regions=_regions_from(body.regions))
    try:
        record = home_layouts.save_layout(
            workspace_id, layout, expected_revision=body.expectedRevision
        )
    except (
        LayoutConflictError,
        PinnedRegionWriteError,
        LayoutPersistenceError,
        LayoutError,
    ) as exc:
        raise _refuse(exc, "layout") from exc
    return {
        "ok": True,
        "revision": record.revision,
        "updatedAt": record.updated_at.isoformat(),
    }


@router.post("/{workspace_id}/home/regions/{region_id}/pin")
async def pin_home_region(
    workspace_id: str, region_id: str, body: RegionPinBody, request: Request
) -> dict[str, Any]:
    """Pin or unpin one region. Presentation only: the referenced resource is
    neither copied nor forked by this operation, and the same service function
    serves the UI, the direct API and the Workspace Agent tool."""
    await _require_writer(request, workspace_id)
    try:
        record = home_layouts.set_region_pinned(
            workspace_id, region_id, pinned=body.pinned, expected_revision=body.expectedRevision
        )
    except (LayoutConflictError, LayoutPersistenceError, LayoutError) as exc:
        raise _refuse(exc, "layout") from exc
    return {
        "ok": True,
        "revision": record.revision,
        "region": next(
            (r.model_dump(mode="json") for r in record.layout.regions if r.id == region_id),
            None,
        ),
    }


@router.get("/{workspace_id}/home/projections")
async def get_home_projections(workspace_id: str, request: Request) -> dict[str, Any]:
    """Compact projections over canonical services, read at call time."""
    user_id = await _require_member(request, workspace_id)
    try:
        return await home_projections.list_projections(user_id, workspace_id)
    except home_projections.WorkspaceNotVisible:
        raise HTTPException(status_code=404, detail="workspace not found") from None


@router.get("/{workspace_id}/home/adaptive")
async def get_home_adaptive(workspace_id: str, request: Request) -> dict[str, Any]:
    """What the unpinned space could show, each candidate with its evidence."""
    user_id = await _require_member(request, workspace_id)
    try:
        return await home_projections.adaptive_items(user_id, workspace_id)
    except home_projections.WorkspaceNotVisible:
        raise HTTPException(status_code=404, detail="workspace not found") from None


@router.post("/{workspace_id}/home/adaptive/dismiss")
async def dismiss_home_adaptive(
    workspace_id: str, body: AdaptiveDismissBody, request: Request
) -> dict[str, Any]:
    """Record "not this" for one adaptive candidate — backend-side, counted.

    This is the negative-reinforcement record: not client-only state, and the
    same store the Workspace Agent tool writes, so a dismissal through chat
    and a dismissal through the API land in the same place.
    """
    user_id = await _require_writer(request, workspace_id)
    record = home_projections.record_dismissal(
        workspace_id, body.itemType, body.itemId, actor=user_id
    )
    return {"ok": True, "dismissed": record["count"], "key": f"{body.itemType}:{body.itemId}"}


@router.post("/{workspace_id}/home/adaptive/compose")
async def compose_home_adaptive(
    workspace_id: str, body: AdaptiveComposeBody, request: Request
) -> dict[str, Any]:
    """The Agent's write path: fill the unpinned space, leave pinned space alone.

    The same service function the Workspace Agent's chat tool calls — no
    browser/UI automation anywhere in the Agent's path to its own Home.
    """
    await _require_writer(request, workspace_id)
    regions = _regions_from(body.regions)
    try:
        record = home_layouts.compose_adaptive(
            workspace_id, regions, expected_revision=body.expectedRevision
        )
    except (
        LayoutConflictError,
        PinnedRegionWriteError,
        LayoutPersistenceError,
        LayoutError,
    ) as exc:
        raise _refuse(exc, "adaptive composition") from exc
    return _layout_dict(record)
