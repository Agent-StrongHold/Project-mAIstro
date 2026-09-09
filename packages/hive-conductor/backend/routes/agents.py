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

import hashlib
import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request, Response
from models.schemas import Agent
from pydantic import BaseModel, ConfigDict, Field
from services.agent_materialization import (
    AgentDefinitionRejected,
    AgentScannerUnavailable,
    ScanBudgetExceeded,
    agent_id_for,
    delete_agent_definition,
    scan_config,
    slugify_agent_name,
    update_agent_definition,
    upsert_agent_definition,
    workspace_agents,
)
from services.workspace_authority import is_member, member_role

from routes.audit import log_audit

logger = logging.getLogger("hive.agents")

router = APIRouter(tags=["agents"])

# `scan_config` / `ScanBudgetExceeded` are re-exported on purpose: the HITL
# door and the chat gate import the Warden config walk from this module, and
# the walk now lives with the one writer it gates
# (`services.agent_materialization`).


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
    # Stored only through the materialization service -- the one writer for
    # this store -- so a created agent is scanned and provenance-stamped like
    # every other definition.
    agent = await _store_or_refuse(upsert_agent_definition(agent, source="crud"))
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
    updates = body.model_dump(exclude_none=True)
    await _store_or_refuse(update_agent_definition(agent_id, updates, source="crud"))
    agent = stores.agents[agent_id]
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
    delete_agent_definition(agent_id)
    log_audit("agent_delete", "system", target=agent_id)


async def _store_or_refuse(awaitable):
    """Await a service definition write and map its fail-closed refusals to
    the HTTP contract Forge set: flagged is 400, a scanner that cannot run is
    503, an unscannable config is 413 -- and nothing is stored in any of
    them."""
    try:
        return await awaitable
    except AgentDefinitionRejected as exc:
        raise HTTPException(
            status_code=400, detail=f"agent rejected by security scan: {exc}"
        ) from exc
    except AgentScannerUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="agent unavailable: the security scan could not run; nothing was stored",
        ) from exc
    except ScanBudgetExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


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

    description: str = Field(min_length=1, max_length=4000)
    #: The strategies the runtime actually ships (`maistro.agents.strategies`:
    #: react, direct, plan_execute, delegate) -- the same four the Builder
    #: offers. Anything else is an invalid configuration, not an artifact.
    strategy: Literal["react", "plan_execute", "direct", "delegate"] = "react"
    model: str = Field(min_length=1, default="gpt-4.1")
    workspace_id: str | None = None


#: How a description binds capabilities (#294). The roster's execution path
#: (`services/agent_invocation.resolve_agent_task` / `pulse_roster`) dispatches
#: on declared capabilities, so a forged agent that declared none would be
#: undispatchable. Substrings of the lowercased description, in map order;
#: the map is a versioned product contract, not a silent heuristic.
_FORGE_CAPABILITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("research", ("research", "search", "analy", "summar", "competitive", "trend", "report")),
    ("code", ("code", "refactor", "debug", "program", "software", "review")),
    ("missions", ("mission", "orchestrat", "plan", "coordinat", "project")),
    ("tools", ("tool", "api", "integrat", "automat", "workflow")),
    ("monitoring", ("monitor", "health", "uptime", "alert", "watch")),
    ("security", ("security", "vulnerab", "penetration", "audit", "exploit")),
    ("memory", ("memory", "embedding", "pattern", "recall", "forget")),
    ("ha_control", ("home assistant", "iot", "smart home", "thermostat", "smart light")),
    ("chat", ("chat", "conversation", "assistant", "support", "answer")),
)
_FORGE_DEFAULT_CAPABILITY = "general"


def _forge_capabilities(description: str) -> list[str]:
    """The capabilities a description binds, deterministically.

    Every forged agent gets at least one capability so the execution path
    can dispatch to it like any other roster member.
    """
    text = description.lower()
    bound = [
        cap for cap, keywords in _FORGE_CAPABILITY_KEYWORDS if any(k in text for k in keywords)
    ]
    return bound or [_FORGE_DEFAULT_CAPABILITY]


def _forge_fingerprint(
    *, workspace_id: str | None, description: str, strategy: str, model: str
) -> str:
    """The content hash behind artifact identity: the same request forges
    the same artifact (idempotent), any changed field forges a new one."""
    payload = "\x1f".join((workspace_id or "", description, strategy, model))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


@router.post("/forge", response_model=Agent, status_code=201)
async def forge_agent(body: ForgeAgentBody, request: Request, response: Response) -> Agent:
    """Forge one agent artifact -- the contract #294 pins.

    - **Deterministic generation.** The artifact (name, soul, capabilities,
      strategy) is derived from the request alone; no random identifiers and
      no LLM -- the description becomes the soul verbatim. The id embeds a
      content fingerprint, so re-submitting the same request returns the
      same durable artifact (idempotent, 200) instead of piling up drafts,
      and a changed request forges a new artifact (201).
    - **Schema validation.** `strategy` must be one the runtime ships; a
      missing or oversized description is a 422, not an artifact.
    - **Capability binding.** Capabilities come from the description via
      `_FORGE_CAPABILITY_KEYWORDS`, and the artifact is keyed the way the
      roster resolves (`{workspace}.{name}`, `agent_id_for`), so the normal
      execution path -- `resolve_agent` / `resolve_agent_task` /
      `pulse_roster` -- dispatches to it like any materialized spawn.
    - **Security scan, fail-closed.** Every text field of the artifact is
      Warden-scanned (`scan_config`, `user_input` boundary) *before* the
      artifact is stored. Flagged is a 400, a scanner that cannot run is a
      503, and neither stores anything: a scan that did not complete can
      never surface as a forged state.
    - **Durable identity + validation provenance.** The stored record
      carries `config.forge` -- spec version, what was generated from, and
      the scan verdict with a timestamp -- and `GET /v1/agents/{id}`
      reloads it.

    What Forge does *not* claim: no publish step and no versioning -- a
    re-forge of the same spec returns the stored artifact unchanged.
    """
    if body.workspace_id and not await _is_workspace_owner(_user_id(request), body.workspace_id):
        raise HTTPException(status_code=403, detail="only a workspace owner can add agents to it")

    t = _now()
    fingerprint = _forge_fingerprint(
        workspace_id=body.workspace_id,
        description=body.description,
        strategy=body.strategy,
        model=body.model,
    )
    # The name carries the fingerprint so the roster's spawn-name resolution
    # (`{workspace}.{spawn}`) finds this artifact by name alone -- the same
    # convention `materialize_workspace_agents` keys persona spawns by.
    name = f"forge-{slugify_agent_name(body.description)}-{fingerprint}"
    aid = agent_id_for(body.workspace_id, name) if body.workspace_id else name

    existing = stores.agents.get(aid)
    if existing is not None:
        # Idempotent re-submission: the same spec forges the same artifact.
        response.status_code = 200
        return existing

    capabilities = _forge_capabilities(body.description)
    artifact_for_scan = {
        "name": name,
        "description": body.description,
        "capabilities": capabilities,
        "config": {"strategy": body.strategy, "model": body.model, "role": "worker"},
    }
    try:
        scan = await scan_config(artifact_for_scan)
    except ScanBudgetExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("agent forge scan failed closed for %s: %s", aid, exc)
        raise HTTPException(
            status_code=503,
            detail="forge unavailable: the security scan could not run; no artifact was stored",
        ) from exc
    if scan["findings"]:
        raise HTTPException(
            status_code=400,
            detail=f"forged agent rejected by security scan: {'; '.join(scan['findings'])}",
        )

    agent = Agent(
        id=aid,
        workspace_id=body.workspace_id,
        name=name,
        description=body.description,
        model=body.model,
        status="idle",
        capabilities=capabilities,
        skills=[],
        current_mission=None,
        tasks_completed=0,
        avg_response_time_ms=0.0,
        last_active=t,
        created_at=t,
        config={
            "strategy": body.strategy,
            "role": "worker",
            "soul": body.description,
            "forge": {
                "spec": 1,
                "generated_from": {
                    "description": body.description,
                    "strategy": body.strategy,
                    "model": body.model,
                },
                "scan": {
                    "boundary": "user_input",
                    "status": scan["status"],
                    "findings": scan["findings"],
                    "scanned_at": t.isoformat(),
                },
            },
        },
    )
    # Stored only through the materialization service -- the one writer for
    # this store -- with Forge's already-completed clean verdict recorded in
    # the row's provenance beside the config's own `forge` block.
    agent = await _store_or_refuse(upsert_agent_definition(agent, source="forge", scan=scan))
    log_audit(
        "agent_forge",
        "system",
        target=aid,
        detail={"name": name, "capabilities": capabilities, "scan": scan["status"]},
    )
    return agent
