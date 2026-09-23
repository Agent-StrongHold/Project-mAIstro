"""The one stable Workspace Agent per Workspace (#1037, ADR-092326-7ed7).

Every Workspace has exactly one persistent Workspace Agent: a canonical row in
the one product roster (`stores.agents`, #840), materialized on first need
through `services.agent_materialization` -- the roster's only writer -- under a
deterministic id. Its persona is a template reference (default
`program_manager`) held on the row; swapping it rewrites that attribute and
never the id.

The id lives in its own `workspace-agent:` namespace so no other producer can
mint it: persona spawns and chat-created actions key `{workspace}.{name}`,
CRUD rows are uuid4, Forge rows `forge-*`, manifest rows their bare names.
"""

from __future__ import annotations

import asyncio
import re
import weakref
from datetime import UTC, datetime
from typing import Any

import stores
from config import get_settings
from models.schemas import Agent

from services import workspace_authority
from services.agent_materialization import update_agent_definition, upsert_agent_definition

DEFAULT_PERSONA_TEMPLATE_ID = "program_manager"
#: Provenance source stamped on the Workspace Agent's row.
WORKSPACE_AGENT_SOURCE = "workspace-agent"
_PERSONA_TEMPLATE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Weak values: a lock lives only while a coroutine holds or awaits it, so no
# lock outlives the event loop it was first contended on.
_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


class WorkspaceNotFound(LookupError):
    """The canonical Workspace store has no such Workspace; no Agent is made."""


class WorkspaceAgentConflict(RuntimeError):
    """The Workspace Agent's id holds a row that belongs to another Workspace."""


def workspace_agent_id(workspace_id: str) -> str:
    """The Workspace Agent's stable id; a pure function of the Workspace id."""
    return f"workspace-agent:{workspace_id}"


def persona_template_id(agent: Agent) -> str:
    """The persona template the Workspace Agent currently runs."""
    persona = agent.config.get("persona") if isinstance(agent.config, dict) else None
    template = persona.get("template_id") if isinstance(persona, dict) else None
    return str(template or DEFAULT_PERSONA_TEMPLATE_ID)


def _lock_for(workspace_id: str) -> asyncio.Lock:
    lock = _locks.get(workspace_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[workspace_id] = lock
    return lock


def _validate_persona(template_id: str) -> str:
    if not isinstance(template_id, str) or not _PERSONA_TEMPLATE_ID.fullmatch(template_id):
        raise ValueError(f"not a persona template id: {template_id!r}")
    return template_id


def _persona_config(config: dict[str, Any], template_id: str) -> dict[str, Any]:
    updated = dict(config)
    updated["workspace_agent"] = True
    updated["persona"] = {"template_id": template_id}
    return updated


async def _existing_or_materialized(workspace_id: str) -> Agent:
    """Caller holds the Workspace's lock."""
    if await workspace_authority.get_view(workspace_id) is None:
        raise WorkspaceNotFound(workspace_id)
    aid = workspace_agent_id(workspace_id)
    existing = stores.agents.get(aid)
    if existing is not None:
        if existing.workspace_id != workspace_id:
            raise WorkspaceAgentConflict(
                f"{aid} is held by a row of workspace {existing.workspace_id!r}"
            )
        return existing
    now = datetime.now(UTC)
    definition = Agent(
        id=aid,
        workspace_id=workspace_id,
        name=aid,
        description="Workspace Agent",
        model=get_settings().chat_default_model,
        status="idle",
        last_active=now,
        created_at=now,
        config=_persona_config({}, DEFAULT_PERSONA_TEMPLATE_ID),
    )
    return await upsert_agent_definition(definition, source=WORKSPACE_AGENT_SOURCE)


async def resolve_workspace_agent(workspace_id: str) -> Agent:
    """Return the Workspace's single canonical Agent, materializing it once.

    Concurrent first calls converge: in-process they serialize on the
    Workspace's lock, and across processes the deterministic id makes every
    writer upsert the same roster row rather than add one. A Workspace the
    canonical store does not hold -- never created, or deleted -- raises
    `WorkspaceNotFound` and writes nothing.
    """
    async with _lock_for(workspace_id):
        return await _existing_or_materialized(workspace_id)


async def set_workspace_agent_persona(workspace_id: str, template_id: str) -> Agent:
    """Swap the Workspace Agent's persona; its id and creation stay as they were."""
    template_id = _validate_persona(template_id)
    async with _lock_for(workspace_id):
        agent = await _existing_or_materialized(workspace_id)
        return await update_agent_definition(
            agent.id,
            {"config": _persona_config(agent.config, template_id)},
            source=WORKSPACE_AGENT_SOURCE,
        )
