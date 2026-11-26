"""Workspace proactive-discovery routes (#1051).

A thin adapter over `services.discovery`, with the Home router's authority
shape: reads and writes are Workspace-member-scoped and fail closed — a
non-member gets the same 404 a missing Workspace gets, and a viewer member
cannot change configuration, trigger cycles or feed back. The mutating
routes are classified in `quality/shipped-surface-truth.json` with the
canonical effect each one's service performs; there is no second write path.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from services import discovery
from services.request_principal import require_actor_id
from services.workspace_authority import member_role, visible_view

router = APIRouter(tags=["discovery"])
logger = logging.getLogger("hive.discovery")


async def _require_member(request: Request, workspace_id: str) -> str:
    """The actor, after a membership check that cannot be skipped.

    Same non-existence-oracle contract as Home: both 404s look identical.
    """
    user_id = require_actor_id(request)
    if await visible_view(user_id, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return user_id


async def _require_writer(request: Request, workspace_id: str) -> str:
    user_id = await _require_member(request, workspace_id)
    if await member_role(user_id, workspace_id) == "viewer":
        raise HTTPException(
            status_code=403, detail="read-only Workspace members cannot change discovery"
        )
    return user_id


class DiscoveryConfigBody(BaseModel):
    """A partial config update. Only provided fields change."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool | None = None
    source_binding_id: str | None = None
    curator_binding_id: str | None = None
    curator_model: str | None = None
    watch_topics: list[str] | None = None
    min_scout_score: float | None = None
    max_candidates_per_cycle: int | None = None
    max_surfaced: int | None = None
    daily_fetch_budget: int | None = None
    daily_curate_budget: int | None = None
    sources_count: int | None = None


class DiscoveryTriggerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(
        default="", description="Parent Project for the Run; defaults to the Workspace root"
    )


class DiscoveryFeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(description="keep | dismiss")


@router.get("/{workspace_id}/discovery/config")
async def get_discovery_config(workspace_id: str, request: Request) -> dict[str, Any]:
    user_id = await _require_member(request, workspace_id)
    config = discovery.get_config(workspace_id)
    # Reading your own membership scope; the config itself is not secret.
    _ = user_id
    return config


@router.put("/{workspace_id}/discovery/config")
async def put_discovery_config(
    workspace_id: str, body: DiscoveryConfigBody, request: Request
) -> dict[str, Any]:
    user_id = await _require_writer(request, workspace_id)
    changes = body.model_dump(exclude_none=True)
    try:
        return discovery.update_config(workspace_id, changes, actor=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{workspace_id}/discovery/run")
async def trigger_discovery(
    workspace_id: str, body: DiscoveryTriggerBody, request: Request
) -> dict[str, Any]:
    user_id = await _require_writer(request, workspace_id)
    project_id = body.project_id.strip() or workspace_id
    try:
        return await discovery.run_discovery_cycle(
            workspace_id,
            project_id,
            user_id,
            actor_id=user_id,
            admission_source="discovery_manual",
        )
    except discovery.DiscoveryNotVisible as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    except discovery.DiscoveryCycleRefused as exc:
        # Budget exhaustion / disabled feature is a clean stop, surfaced as
        # 409 with the reason — not a 500 and not a silent no-op.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{workspace_id}/discovery/items")
async def get_discovery_items(workspace_id: str, request: Request) -> dict[str, Any]:
    user_id = await _require_member(request, workspace_id)
    try:
        return await discovery.surfaced_items(user_id, workspace_id)
    except discovery.DiscoveryNotVisible as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc


@router.post("/{workspace_id}/discovery/items/{fingerprint}/feedback")
async def post_discovery_feedback(
    workspace_id: str, fingerprint: str, body: DiscoveryFeedbackBody, request: Request
) -> dict[str, Any]:
    user_id = await _require_writer(request, workspace_id)
    try:
        return await discovery.record_feedback(
            workspace_id, fingerprint, body.action, actor=user_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="discovery item not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{workspace_id}/discovery/status")
async def get_discovery_status(workspace_id: str, request: Request) -> dict[str, Any]:
    user_id = await _require_member(request, workspace_id)
    _ = user_id
    return {
        "workspace_id": workspace_id,
        "config": discovery.get_config(workspace_id),
        "budget": discovery.budget_status(workspace_id),
        "preferences": discovery.category_preferences(workspace_id),
        "dag_id": discovery.DISCOVERY_DAG_ID,
    }


__all__ = ["router"]
