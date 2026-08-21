"""Materialize a workspace's persona into real, workspace-scoped Agent
records -- the missing piece connecting
`maistro.personas.expander.expand_persona()` (persona -> named agent
roster) to hive-conductor's `stores.agents` (the roster
`GET/POST /v1/agents` actually reads). Every persona is treated
identically here: `pm_fleet` is just one premade template like any other
-- whichever persona a workspace adopts, its own declared `spawns` become
real, visible agents through the exact same path, no special-casing.

`expand_persona()`'s `ExpandedAgent.active` governance flag ("flipped by
the review gate") has no reviewer anywhere in the codebase to flip it --
that comment describes a mechanism that was never built. A workspace's own
agents are usable as soon as the workspace exists, same as everything else
a persona declares (tools, checklist, theme) -- there's nothing to wait on.
"""

from __future__ import annotations

from datetime import UTC, datetime

import stores
from config import get_settings
from models.schemas import Agent

from maistro.personas.expander import expand_persona
from maistro.personas.schema import PersonaTemplate

from .model_store import register_pop_hook


def agent_id_for(workspace_id: str, spawn_agent: str) -> str:
    """Deterministic, workspace-scoped agent id. Stable across
    re-materialization: creating/updating the same workspace's agents again
    overwrites the same records rather than piling up duplicates."""
    return f"{workspace_id}.{spawn_agent}"


def materialize_workspace_agents(workspace_id: str, template: PersonaTemplate) -> list[Agent]:
    """Expand `template` and write one real Agent record per declared spawn
    into `stores.agents`, tagged with `workspace_id`. Returns the created
    records. A `kind: department` template (no spawns) materializes to an
    empty list -- nothing to do, not an error."""
    expanded = expand_persona(template)
    default_model = get_settings().chat_default_model
    now = datetime.now(UTC)
    agents: list[Agent] = []
    for expanded_agent in expanded.agents:
        recipe = expanded_agent.recipe
        spawn_agent = recipe.name.split(".", 1)[-1]
        aid = agent_id_for(workspace_id, spawn_agent)
        agent = Agent(
            id=aid,
            workspace_id=workspace_id,
            name=recipe.name,
            description=recipe.description,
            model=default_model,
            status="idle",
            capabilities=list(recipe.tools),
            skills=list(expanded_agent.skills),
            created_at=now,
            last_active=now,
        )
        stores.agents[aid] = agent
        agents.append(agent)
    return agents


def workspace_agents(workspace_id: str) -> list[Agent]:
    """Every agent materialized for this workspace."""
    return [a for a in stores.agents.values() if a.workspace_id == workspace_id]


def delete_workspace_agents(workspace_id: str) -> None:
    """Delete every materialized agent owned by ``workspace_id``.

    Called as a pre-delete lifecycle hook for the workspaces store so both the
    in-memory and persisted agent records disappear before their ownership
    record does. Iterating over a snapshot avoids mutating the store while its
    values view is live.
    """
    for agent in list(workspace_agents(workspace_id)):
        stores.agents.pop(agent.id, None)


# Register once when the workspace routes import this module. Keeping the
# cascade at the store lifecycle boundary means future non-HTTP deletion paths
# cannot accidentally recreate permanent orphan agents.
register_pop_hook("workspaces", delete_workspace_agents)
