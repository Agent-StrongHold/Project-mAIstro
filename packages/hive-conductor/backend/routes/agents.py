"""Agent roster — PM Fleet legacy mode, generic CRUD, and now workspace-scoped
real agents (Persona/Workspace system).

An optional `workspace_id` query param (list/get) or body field
(create/forge) resolves the caller's own materialized roster
(`services/agent_materialization.py`, backing any persona -- `pm_fleet` is
just one premade template, not special-cased here) for that specific
workspace. Omitted -- every caller before this parameter existed -- keeps
the exact old behavior: `is_pm_poc_mode()` branches between the hardcoded
PM Fleet roster and the flat global `stores.agents` registry.

Invoking an agent (`POST /{agent_id}/invoke`) is deliberately NOT made
workspace-aware here: that would require wiring the actual per-persona
dispatch/spawner runtime (which agent runs which LLM call with which
tools), a separate, substantial piece of work. This slice only makes a
workspace's own agents real and *visible*.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from models.schemas import Agent
from pydantic import BaseModel, ConfigDict
from services.agent_materialization import workspace_agents
from services.engine import get_engine
from services.pm_fleet import is_pm_poc_mode, list_pm_agents

from maistro.agents.pm_capabilities import CAPABILITY_TO_WORK_ITEM, is_gated
from routes.audit import log_audit

logger = logging.getLogger("hive.agents")

router = APIRouter(tags=["agents"])


def _use_secret(store: object, user_id: str, provider_id: str) -> str | None:
    """Single allowlisted callsite for use_secret — lambda is centralised here."""
    try:
        return store.use_secret(user_id, provider_id, lambda s: s)  # type: ignore[union-attr]
    except Exception:
        return None


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


def _build_invoke_context(user_id: str) -> dict[str, Any]:
    """Build program_context with credentials for agent invocation."""
    from services import program_store as prog
    from services import user_credentials as cred_svc

    try:
        from maistro.agents.program_context import context_for_task

        ctx = prog.get_context(user_id)
        pctx = context_for_task(ctx)
    except Exception:
        pctx = {}
    # Inject Atlassian PATs
    store = cred_svc.get_credential_store()
    if store:
        pats: dict[str, str | None] = {}
        for pid, key in [("atlassian_server_jira", "jira"), ("confluence", "confluence")]:
            try:
                if store.has_secret(user_id, pid):
                    pats[key] = _use_secret(store, user_id, pid)
            except Exception:
                pass
        if pats:
            pctx["atlassian_pats"] = pats
    return pctx


@router.get("", response_model=list[Agent])
def list_agents(request: Request, workspace_id: str | None = None) -> list[Agent]:
    uid = _user_id(request)
    if workspace_id and _is_member(uid, workspace_id):
        return workspace_agents(workspace_id)
    if is_pm_poc_mode():
        engine = get_engine()
        raw_tasks = [r.raw for r in engine.list_tasks(user_id=uid)]
        return list_pm_agents(raw_tasks, user_id=uid)
    return [a for a in stores.agents.values() if a.workspace_id is None]


@router.get("/{agent_id}", response_model=Agent)
def get_agent(agent_id: str, request: Request, workspace_id: str | None = None) -> Agent:
    uid = _user_id(request)
    if workspace_id and _is_member(uid, workspace_id):
        agent = stores.agents.get(agent_id)
        if agent is None or agent.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="agent not found")
        return agent
    if is_pm_poc_mode():
        for agent in list_agents(request):
            if agent.id == agent_id:
                return agent
        raise HTTPException(status_code=404, detail="agent not found")
    agent = stores.agents.get(agent_id)
    if agent is None or agent.workspace_id is not None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


class InvokeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    capability: str
    payload: dict[str, Any] = {}


@router.post("/{agent_id}/invoke")
async def invoke_agent(agent_id: str, body: InvokeBody, request: Request) -> dict[str, Any]:
    if not is_pm_poc_mode():
        raise HTTPException(status_code=404, detail="Agent invoke only available in PM POC mode")
    if is_gated(body.capability):
        work_type = CAPABILITY_TO_WORK_ITEM.get(body.capability, "work item")
        raise HTTPException(
            status_code=403,
            detail=(
                f"Capability '{body.capability}' posts to Jira. "
                f"Use POST /v1/work-items/suggest with work_type '{work_type}' "
                "— clarify, edit, then confirm."
            ),
        )
    uid = _user_id(request)
    # Execute directly via the same tool execution the chat uses — real data, no queue
    from services.chat_completion import _execute_tool

    result = await _execute_tool(body.capability, body.payload, uid)
    log_audit(
        "agent_invoke",
        uid,
        target=agent_id,
        detail={
            "capability": body.capability,
            "result_keys": list(result.keys()) if isinstance(result, dict) else [],
        },
    )
    return {"status": "completed", "capability": body.capability, "result": result}


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
    if body.workspace_id:
        if not _is_workspace_owner(_user_id(request), body.workspace_id):
            raise HTTPException(
                status_code=403, detail="only a workspace owner can add agents to it"
            )
    elif is_pm_poc_mode():
        raise HTTPException(status_code=403, detail="PM fleet is read-only in POC mode")
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
    if existing is not None and existing.workspace_id:
        if not _is_workspace_owner(_user_id(request), existing.workspace_id):
            raise HTTPException(
                status_code=403, detail="only a workspace owner can update this agent"
            )
    elif is_pm_poc_mode():
        raise HTTPException(status_code=403, detail="PM fleet is read-only in POC mode")
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
    if existing is not None and existing.workspace_id:
        if not _is_workspace_owner(_user_id(request), existing.workspace_id):
            raise HTTPException(
                status_code=403, detail="only a workspace owner can delete this agent"
            )
    elif is_pm_poc_mode():
        raise HTTPException(status_code=403, detail="PM fleet is read-only in POC mode")
    if agent_id not in stores.agents:
        raise HTTPException(status_code=404, detail="agent not found")
    stores.agents.pop(agent_id)
    log_audit("agent_delete", "system", target=agent_id)


@router.post("/{agent_id}/scan")
def scan_agent(agent_id: str) -> dict:
    if is_pm_poc_mode():
        from maistro.agents.pm_fleet import get_pm_def

        if get_pm_def(agent_id) is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return {"findings": [], "status": "clean"}
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
    if body.workspace_id:
        if not _is_workspace_owner(_user_id(request), body.workspace_id):
            raise HTTPException(
                status_code=403, detail="only a workspace owner can add agents to it"
            )
    elif is_pm_poc_mode():
        raise HTTPException(status_code=403, detail="PM fleet is read-only in POC mode")
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
