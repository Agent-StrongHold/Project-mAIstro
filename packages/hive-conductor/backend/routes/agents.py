"""Agent roster — generic CRUD over workspace-scoped and global agents.

An optional `workspace_id` query param (list/get) or body field
(create/forge) resolves the caller's own materialized roster
(`services/agent_materialization.py`, backing any persona -- `pm_fleet` is
just one premade template, not special-cased here) for that specific
workspace. Omitted, the flat global `stores.agents` registry answers.

Workspace authorization comes only from the canonical Workspace membership
store through `services.workspace_authority` (#37). Hive's legacy Workspace
records are migration input, never a live authorization source.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from models.schemas import Agent
from pydantic import BaseModel, ConfigDict
from services.agent_materialization import workspace_agents
from services.workspace_authority import is_member, member_role

from maistro.security.warden.detector import Warden
from routes.audit import log_audit

logger = logging.getLogger("hive.agents")

router = APIRouter(tags=["agents"])


def _now() -> datetime:
    return datetime.now(UTC)


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("id") or user.get("username") or "dev")


async def _is_member(user_id: str, workspace_id: str) -> bool:
    return await is_member(user_id, workspace_id)


async def _is_workspace_owner(user_id: str, workspace_id: str) -> bool:
    return await member_role(user_id, workspace_id) == "owner"


@router.get("", response_model=list[Agent])
async def list_agents(request: Request, workspace_id: str | None = None) -> list[Agent]:
    uid = _user_id(request)
    if workspace_id and await _is_member(uid, workspace_id):
        return workspace_agents(workspace_id)
    return [a for a in stores.agents.values() if a.workspace_id is None]


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str, request: Request, workspace_id: str | None = None) -> Agent:
    uid = _user_id(request)
    if workspace_id and await _is_member(uid, workspace_id):
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
    workspace_id: str | None = None


@router.post("", response_model=Agent, status_code=201)
async def create_agent(body: CreateAgentBody, request: Request) -> Agent:
    if body.workspace_id and not await _is_workspace_owner(_user_id(request), body.workspace_id):
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
async def update_agent(agent_id: str, body: UpdateAgentBody, request: Request) -> Agent:
    existing = stores.agents.get(agent_id)
    if (
        existing is not None
        and existing.workspace_id
        and not await _is_workspace_owner(_user_id(request), existing.workspace_id)
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
async def delete_agent(agent_id: str, request: Request) -> None:
    existing = stores.agents.get(agent_id)
    if (
        existing is not None
        and existing.workspace_id
        and not await _is_workspace_owner(_user_id(request), existing.workspace_id)
    ):
        raise HTTPException(status_code=403, detail="only a workspace owner can delete this agent")
    if agent_id not in stores.agents:
        raise HTTPException(status_code=404, detail="agent not found")
    stores.agents.pop(agent_id)
    log_audit("agent_delete", "system", target=agent_id)


MAX_SCAN_DEPTH = 32
MAX_SCAN_NODES = 4096
MAX_SCAN_TEXT = 64 * 1024


class ScanBudgetExceeded(Exception):
    """The config is larger or deeper than the scanner will walk."""


def _text_leaves(value: object, *, path: str = "", depth: int = 0) -> Iterator[tuple[str, str]]:
    """Yield every (dotted path, string) pair in a config, in a bounded walk."""
    if depth > MAX_SCAN_DEPTH:
        raise ScanBudgetExceeded(f"config nests deeper than {MAX_SCAN_DEPTH} levels")
    if isinstance(value, str):
        yield path or "<root>", value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            yield from _text_leaves(item, path=child, depth=depth + 1)
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            yield from _text_leaves(item, path=f"{path}[{index}]", depth=depth + 1)


def _warden() -> Warden:
    """One detector for the process."""
    global _warden_instance
    if _warden_instance is None:
        _warden_instance = Warden()
    return _warden_instance


_warden_instance: Warden | None = None


async def scan_config(config: object) -> dict:
    """Scan every string in a configuration at the `user_input` boundary."""
    warden = _warden()
    findings: list[str] = []
    for scanned, (path, text) in enumerate(_text_leaves(config), start=1):
        if scanned > MAX_SCAN_NODES:
            raise ScanBudgetExceeded(f"config holds more than {MAX_SCAN_NODES} values")
        if len(text) > MAX_SCAN_TEXT:
            raise ScanBudgetExceeded(f"{path} is longer than {MAX_SCAN_TEXT} characters")
        verdict = await warden.scan(text, "user_input")
        if not verdict.clean:
            findings.extend(f"{path}: {flag}" for flag in verdict.flags)
    return {"findings": findings, "status": "clean" if not findings else "flagged"}


@router.post("/scan")
async def scan_proposed_config(body: dict) -> dict:
    """Scan a proposed configuration before it is saved."""
    try:
        return await scan_config(body)
    except ScanBudgetExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.post("/{agent_id}/scan")
async def scan_agent(agent_id: str) -> dict:
    """Scan a saved agent's configuration."""
    agent = stores.agents.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    try:
        return await scan_config(agent.model_dump(mode="json"))
    except ScanBudgetExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


class ForgeAgentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    strategy: str = "react"
    model: str = "gpt-4.1"
    workspace_id: str | None = None


@router.post("/forge", response_model=Agent)
async def forge_agent(body: ForgeAgentBody, request: Request) -> Agent:
    if body.workspace_id and not await _is_workspace_owner(_user_id(request), body.workspace_id):
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
