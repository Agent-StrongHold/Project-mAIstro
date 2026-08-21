"""PM fleet agents API — list and invoke project-management agents."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from maistro.agents.pm_fleet import (
    PM_FLEET,
    agent_status_for_user,
    build_task_description,
    fleet_card_dict,
    get_pm_def,
)
from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import TaskQueue, get_task_queue
from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal
from maistro_server.api.schemas import TaskCreatedResponse

router = APIRouter(prefix="/agents", tags=["pm-agents"])


def _poc_enabled() -> bool:
    return os.getenv("MAISTRO_POC_MODE", "").strip().lower() == "pm"


class InvokeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    capability: str
    payload: dict[str, Any] = Field(default_factory=dict)


class FleetAgentCard(BaseModel):
    id: str
    name: str
    tagline: str
    status: str
    capabilities: list[str]
    primary_capability: str
    primary_action_label: str


class FleetListResponse(BaseModel):
    agents: list[FleetAgentCard]


def _owner_id(auth: AuthenticatedPrincipal | None) -> str:
    if auth is None:
        return "dev"
    return auth.user_id


@router.get("", response_model=FleetListResponse)
async def list_pm_agents(
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
) -> FleetListResponse:
    if not _poc_enabled():
        raise HTTPException(status_code=404, detail="PM fleet mode disabled")
    uid = _owner_id(auth)
    items, _ = queue.list_tasks(limit=200, user_id=uid)
    cards = [
        FleetAgentCard(
            **fleet_card_dict(
                defn,
                status=agent_status_for_user(defn, items),
            )
        )
        for defn in PM_FLEET
    ]
    return FleetListResponse(agents=cards)


@router.post("/{agent_id}/invoke", status_code=status.HTTP_202_ACCEPTED)
async def invoke_pm_agent(
    agent_id: str,
    body: InvokeBody,
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
) -> TaskCreatedResponse:
    if not _poc_enabled():
        raise HTTPException(status_code=404, detail="PM fleet mode disabled")
    defn = get_pm_def(agent_id)
    if defn is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        task_type, description = build_task_description(agent_id, body.capability, body.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    uid = _owner_id(auth)
    task = await queue.submit(
        TaskCreate(
            description=description,
            task_type=task_type,
            agent_id=defn.name,
            capability=body.capability,
        ),
        user_id=uid,
    )
    return TaskCreatedResponse(
        task_id=task.task_id,
        status=task.status.value,
        task=task,
    )
