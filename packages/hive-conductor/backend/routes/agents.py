"""Agent roster — generic CRUD over workspace-scoped and global agents.

An optional `workspace_id` query param (list/get) or body field
(create/forge) resolves the caller's own materialized roster
(`services/agent_materialization.py`, backing any persona -- `pm_fleet` is
just one premade template, not special-cased here) for that specific
workspace. Omitted, the flat global `stores.agents` registry answers.

There is no third branch any more (#129). `is_pm_poc_mode()` used to sit
between those two and answer with `maistro.agents.pm_fleet.PM_FLEET`: six
agents belonging to one persona, synthesised per request, visible to every
caller in the deployment regardless of which workspace they were in. A
persona's roster is now the only roster, so a caller who names no workspace
sees the global agents rather than another persona's.

`POST /{agent_id}/invoke` went with it. Its whole gate was that flag, it
dispatched on `body.capability` alone -- `agent_id` reached nothing but the
audit record -- and no frontend called it. ADR-082226-4478's third decision
covers exactly this shape: a single-purpose endpoint retires onto the
general path or is dropped, and there was nothing here to retire onto.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from models.schemas import Agent
from pydantic import BaseModel, ConfigDict
from services.agent_materialization import workspace_agents

from routes.audit import log_audit

logger = logging.getLogger("hive.agents")

router = APIRouter(tags=["agents"])


def _now() -> datetime:
    return datetime.now(UTC)


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("id") or user.get("username") or "dev")


def _is_member(user_id: str, workspace_id: str) -> bool:
    workspace = stores.workspaces.get(workspace_id)
    return workspace is not None and any(m.user_id == user_id for m in workspace.members)


def _is_workspace_owner(user_id: str, workspace_id: str) -> bool:
    workspace = stores.workspaces.get(workspace_id)
    if workspace is None:
        return False
    return any(m.user_id == user_id and m.role == "owner" for m in workspace.members)


@router.get("", response_model=list[Agent])
def list_agents(request: Request, workspace_id: str | None = None) -> list[Agent]:
    uid = _user_id(request)
    if workspace_id and _is_member(uid, workspace_id):
        return workspace_agents(workspace_id)
    return [a for a in stores.agents.values() if a.workspace_id is None]


@router.get("/{agent_id}", response_model=Agent)
def get_agent(agent_id: str, request: Request, workspace_id: str | None = None) -> Agent:
    uid = _user_id(request)
    if workspace_id and _is_member(uid, workspace_id):
        agent = stores.agents.get(agent_id)
        if agent is None or agent.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="agent not found")
        return agent
    agent = stores.agents.get(agent_id)
    if agent is None or agent.workspace_id is not None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


class CreateAgentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    model: str = "gpt-4.1"
    capabilities: list[str] = []
    skills: list[str] = []
    config: dict = {}
    # Attach this agent to a specific workspace instead of the flat global
    # registry -- requires the caller be that workspace's owner.
    workspace_id: str | None = None


@router.post("", response_model=Agent, status_code=201)
def create_agent(body: CreateAgentBody, request: Request) -> Agent:
    if body.workspace_id and not _is_workspace_owner(_user_id(request), body.workspace_id):
        raise HTTPException(status_code=403, detail="only a workspace owner can add agents to it")
    aid = str(uuid4())
    t = _now()
    agent = Agent(
        id=aid,
        workspace_id=body.workspace_id,
        name=body.name,
        description=body.description,
        model=body.model,
        status="idle",
        capabilities=body.capabilities,
        skills=body.skills,
        current_mission=None,
        tasks_completed=0,
        avg_response_time_ms=0.0,
        last_active=t,
        created_at=t,
        config=body.config,
    )
    stores.agents[aid] = agent
    log_audit("agent_create", "system", target=aid, detail={"name": body.name})
    return agent


class UpdateAgentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    description: str | None = None
    model: str | None = None
    capabilities: list[str] | None = None
    skills: list[str] | None = None
    config: dict | None = None
    status: str | None = None


@router.put("/{agent_id}", response_model=Agent)
def update_agent(agent_id: str, body: UpdateAgentBody, request: Request) -> Agent:
    existing = stores.agents.get(agent_id)
    if (
        existing is not None
        and existing.workspace_id
        and not _is_workspace_owner(_user_id(request), existing.workspace_id)
    ):
        raise HTTPException(status_code=403, detail="only a workspace owner can update this agent")
    if agent_id not in stores.agents:
        raise HTTPException(status_code=404, detail="agent not found")
    agent = stores.agents[agent_id]
    updates = body.model_dump(exclude_none=True)
    agent = agent.model_copy(update=updates)
    stores.agents[agent_id] = agent
    log_audit("agent_update", "system", target=agent_id, detail=updates)
    return agent


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, request: Request) -> None:
    existing = stores.agents.get(agent_id)
    if (
        existing is not None
        and existing.workspace_id
        and not _is_workspace_owner(_user_id(request), existing.workspace_id)
    ):
        raise HTTPException(status_code=403, detail="only a workspace owner can delete this agent")
    if agent_id not in stores.agents:
        raise HTTPException(status_code=404, detail="agent not found")
    stores.agents.pop(agent_id)
    log_audit("agent_delete", "system", target=agent_id)


@router.post("/{agent_id}/scan")
def scan_agent(agent_id: str) -> dict:
    if agent_id not in stores.agents:
        raise HTTPException(status_code=404, detail="agent not found")
    return {"findings": [], "status": "clean"}


class ForgeAgentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    strategy: str = "react"
    model: str = "gpt-4.1"
    workspace_id: str | None = None


@router.post("/forge", response_model=Agent)
def forge_agent(body: ForgeAgentBody, request: Request) -> Agent:
    if body.workspace_id and not _is_workspace_owner(_user_id(request), body.workspace_id):
        raise HTTPException(status_code=403, detail="only a workspace owner can add agents to it")
    import random
    import string

    suffix = "".join(random.choices(string.ascii_lowercase, k=6))  # nosec B311 — display-only id suffix; UUID4 is the actual identity
    aid = str(uuid4())
    t = _now()
    agent = Agent(
        id=aid,
        workspace_id=body.workspace_id,
        name=f"forge-{suffix}",
        description=body.description,
        model=body.model,
        status="idle",
        capabilities=[],
        skills=[],
        current_mission=None,
        tasks_completed=0,
        avg_response_time_ms=0.0,
        last_active=t,
        created_at=t,
        config={"strategy": body.strategy, "role": "worker"},
    )
    stores.agents[aid] = agent
    return agent
