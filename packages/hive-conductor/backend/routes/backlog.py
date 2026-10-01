"""Backlog HTTP surface — a thin adapter over the canonical service.

List/board data, detail inspection, and every editing verb (create, edit,
prioritize, reorder, block/unblock, decompose, pin, pause, archive) come from
``services.backlog``. The routes add only: authentication (fail closed with
401 before the service sees an anonymous caller), the version-conflict → 409
mapping that makes optimistic concurrency recoverable, and audit logging.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from services import backlog as backlog_svc
from services.backlog import (
    BacklogError,
    BacklogNotAuthorizedError,
    BacklogNotFoundError,
    VersionConflictError,
)

from routes.audit import log_audit

router = APIRouter(tags=["backlog"])


def _actor(request: Request) -> str:
    """The authenticated principal; an anonymous caller never gets past this.

    Fail closed: no session, no list, no detail, no edit.
    """
    user = getattr(request.state, "user", None) or {}
    actor = str(user.get("id") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="authentication required")
    return actor


def _http_error(exc: BacklogError) -> HTTPException:
    if isinstance(exc, VersionConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "message": "This item changed while you were editing. Reload to see the current version.",
                "current": exc.current.model_dump(mode="json"),
            },
        )
    if isinstance(exc, BacklogNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, BacklogNotAuthorizedError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


class BacklogCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    workspace_id: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    status: str = "todo"
    source: str = ""
    acceptance_evidence: str = ""
    risk: str = "medium"
    autonomy_mode: str = "human-review-required"
    goal_id: str | None = None
    goal_revision: int | None = None
    dependencies: list[str] = []


class BacklogUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    expected_version: int = Field(ge=1)
    changes: dict[str, Any]


class BacklogReorder(BaseModel):
    model_config = ConfigDict(extra="ignore")

    expected_version: int = Field(ge=1)
    rank: float
    status: str | None = None


class BacklogBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    expected_version: int = Field(ge=1)
    reason: str | None = None


class BacklogFlag(BaseModel):
    model_config = ConfigDict(extra="ignore")

    expected_version: int = Field(ge=1)
    reason: str | None = None


class BacklogDecompose(BaseModel):
    model_config = ConfigDict(extra="ignore")

    expected_version: int = Field(ge=1)
    children: list[dict[str, Any]]


@router.get("/v1/backlog")
async def list_backlog(
    request: Request, workspace_id: str | None = None, include_archived: bool = False
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        items = await backlog_svc.list_items(
            actor, workspace_id=workspace_id, include_archived=include_archived
        )
    except BacklogError as exc:
        raise _http_error(exc) from exc
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "authority": dict(backlog_svc.UI_AUTHORITY),
    }


@router.get("/v1/backlog/{item_id}")
async def backlog_detail(item_id: str, request: Request) -> dict[str, Any]:
    actor = _actor(request)
    try:
        return await backlog_svc.get_detail(actor, item_id)
    except BacklogError as exc:
        raise _http_error(exc) from exc


@router.post("/v1/backlog", status_code=201)
async def create_backlog_item(spec: BacklogCreate, request: Request) -> dict[str, Any]:
    actor = _actor(request)
    try:
        item = await backlog_svc.create_item(
            actor,
            title=spec.title.strip(),
            workspace_id=spec.workspace_id,
            description=spec.description,
            priority=spec.priority,
            status=spec.status,  # type: ignore[arg-type]
            source=spec.source,
            acceptance_evidence=spec.acceptance_evidence,
            risk=spec.risk,  # type: ignore[arg-type]
            autonomy_mode=spec.autonomy_mode,  # type: ignore[arg-type]
            goal_id=spec.goal_id,
            goal_revision=spec.goal_revision,
            dependencies=spec.dependencies,
        )
    except BacklogError as exc:
        raise _http_error(exc) from exc
    log_audit("backlog.item.created", actor, target=item.id, detail={"title": item.title})
    return item.model_dump(mode="json")


@router.patch("/v1/backlog/{item_id}")
async def update_backlog_item(
    item_id: str, body: BacklogUpdate, request: Request
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        item = await backlog_svc.update_item(
            actor, item_id, expected_version=body.expected_version, changes=body.changes
        )
    except BacklogError as exc:
        raise _http_error(exc) from exc
    log_audit(
        "backlog.item.updated",
        actor,
        target=item_id,
        detail={"version": item.version, "fields": sorted(body.changes)},
    )
    return item.model_dump(mode="json")


@router.post("/v1/backlog/{item_id}/reorder")
async def reorder_backlog_item(
    item_id: str, body: BacklogReorder, request: Request
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        item = await backlog_svc.reorder_item(
            actor,
            item_id,
            expected_version=body.expected_version,
            rank=body.rank,
            status=body.status,
        )
    except BacklogError as exc:
        raise _http_error(exc) from exc
    log_audit("backlog.item.reordered", actor, target=item_id, detail={"rank": body.rank})
    return item.model_dump(mode="json")


@router.post("/v1/backlog/{item_id}/block")
async def block_backlog_item(item_id: str, body: BacklogBlock, request: Request) -> dict[str, Any]:
    actor = _actor(request)
    try:
        item = await backlog_svc.set_blocked(
            actor,
            item_id,
            expected_version=body.expected_version,
            blocked=True,
            reason=body.reason,
        )
    except BacklogError as exc:
        raise _http_error(exc) from exc
    log_audit("backlog.item.blocked", actor, target=item_id, detail={"reason": body.reason})
    return item.model_dump(mode="json")


@router.post("/v1/backlog/{item_id}/unblock")
async def unblock_backlog_item(
    item_id: str, body: BacklogBlock, request: Request
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        item = await backlog_svc.set_blocked(
            actor, item_id, expected_version=body.expected_version, blocked=False
        )
    except BacklogError as exc:
        raise _http_error(exc) from exc
    log_audit("backlog.item.unblocked", actor, target=item_id)
    return item.model_dump(mode="json")


def _flag_endpoint(flag: str, action: str, value: bool):
    async def _endpoint(item_id: str, body: BacklogFlag, request: Request) -> dict[str, Any]:
        actor = _actor(request)
        try:
            item = await backlog_svc.set_operator_flag(
                actor,
                item_id,
                expected_version=body.expected_version,
                flag=flag,
                value=value,
                reason=body.reason,
            )
        except BacklogError as exc:
            raise _http_error(exc) from exc
        log_audit(f"backlog.item.{action}", actor, target=item_id)
        return item.model_dump(mode="json")

    return _endpoint


# Pin / pause / archive plus their clears: one durable operator control each,
# all through the same service entry point so no control has a side door.
router.add_api_route(
    "/v1/backlog/{item_id}/pin", _flag_endpoint("pinned", "pinned", True), methods=["POST"]
)
router.add_api_route(
    "/v1/backlog/{item_id}/unpin", _flag_endpoint("pinned", "unpinned", False), methods=["POST"]
)
router.add_api_route(
    "/v1/backlog/{item_id}/pause", _flag_endpoint("paused", "paused", True), methods=["POST"]
)
router.add_api_route(
    "/v1/backlog/{item_id}/resume", _flag_endpoint("paused", "resumed", False), methods=["POST"]
)
router.add_api_route(
    "/v1/backlog/{item_id}/archive", _flag_endpoint("archived", "archived", True), methods=["POST"]
)
router.add_api_route(
    "/v1/backlog/{item_id}/restore", _flag_endpoint("archived", "restored", False), methods=["POST"]
)


@router.post("/v1/backlog/{item_id}/decompose")
async def decompose_backlog_item(
    item_id: str, body: BacklogDecompose, request: Request
) -> dict[str, Any]:
    actor = _actor(request)
    try:
        children = await backlog_svc.decompose_item(
            actor, item_id, expected_version=body.expected_version, children=body.children
        )
    except BacklogError as exc:
        raise _http_error(exc) from exc
    log_audit(
        "backlog.item.decomposed",
        actor,
        target=item_id,
        detail={"children": [c.id for c in children]},
    )
    return {"parent_id": item_id, "children": [c.model_dump(mode="json") for c in children]}
