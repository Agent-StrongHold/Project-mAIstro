"""Resolve a queued task against a workspace's own agent roster (#129).

Replaces `services/pm_fleet.py::invoke_pm_agent`, which resolved an agent
against `maistro.agents.pm_fleet.PM_FLEET` -- six names, fixed at import,
belonging to one persona. A workspace runs a *persona*, and `pm_fleet` is one
`PersonaTemplate` among others (ADR-082226-4478), so resolution has to read the
roster `services/agent_materialization.py` actually materialised for the
workspace rather than a table naming one persona's agents.

**A bare agent name is resolved within the workspace first.** Every producer of
one -- `agent_for_work_item()`, `autonomous_pulse_candidates()` -- names a spawn
(`delivery`), while `materialize_workspace_agents` keys the record by
`agent_id_for(workspace_id, spawn)` (`ws-7.delivery`). Looking up the bare name
alone would miss every materialised agent there is; looking up only the scoped
one would miss the global, workspace-less records `stores.agents` also holds.
Both, scoped first, so a workspace's own agent always wins over a global agent
of the same name.

**`task_type` is the agent's own name.** `PmAgentDef` carried a separate
`task_type` that diverged from the agent name for exactly two of six entries
(`program_manager` -> `program_management`, `risk_dependency` -> `risk`), and
`maistro.agents.intents._PM_ROUTING` existed to map it back. Nothing on the
queue path reads it: `TaskCreate.task_type` is carried through `queue`,
`admission` and `runner` as metadata, the task carries `agent_id` explicitly
alongside it, and the one caller of `IntentRegistry.resolve()` is
`maistro.conduit`, which takes its task type from the classifier rather than
from a queued task. So the divergence bought a label -- and a persona that
never declared a `task_type` could not have supplied one anyway.
"""

from __future__ import annotations

from typing import Any

import stores
from models.schemas import Agent

from maistro.agents.hyperagent import RosterAgent
from services.agent_materialization import agent_id_for, workspace_agents


def _capabilities_of(agent: Agent) -> frozenset[str]:
    """Everything this agent can be asked to do, from both fields.

    The two rosters fill them differently: `materialize_workspace_agents` maps
    a spawn's `tools` to `capabilities` and its `skills` to `skills`, and
    `pm_fleet.yaml` declares every capability under `skills` with `tools: []`.
    A caller naming a capability does not know, and should not have to know,
    which side of that split it landed on.
    """
    return frozenset(agent.skills) | frozenset(agent.capabilities)


def _spawn_name(agent: Agent) -> str:
    """The agent's own name, undotted.

    `expand_persona` names a recipe `<persona>.<spawn>`, so `agent.name` reads
    `pm_fleet.delivery`. The persona half is the workspace's, not the agent's,
    and repeating it in a task label says nothing the `workspace_id` on the
    same record does not already say.
    """
    return agent.name.rsplit(".", 1)[-1]


def resolve_agent(agent_id: str, *, workspace_id: str | None = None) -> Agent | None:
    """The record for `agent_id`, scoped to `workspace_id` when it names one."""
    if workspace_id:
        scoped = stores.agents.get(agent_id_for(workspace_id, agent_id))
        if scoped is not None:
            return scoped
    return stores.agents.get(agent_id)


def pulse_roster(workspace_id: str | None = None) -> list[RosterAgent]:
    """What this workspace can be asked to do, for `propose_autonomous_actions`.

    Ordered the way `resolve_agent` resolves: this workspace's own materialized
    agents first, then the global workspace-less records `stores.agents` also
    holds. The pulse matches a capability to the *first* declarer, so that
    ordering is what makes a workspace's own agent win over a global agent
    declaring the same capability — the same precedence a queued task already
    gets, now applied one step earlier, when the action is proposed.

    Names are spawn names (`delivery`, not `ws-7.delivery`) because that is
    what `resolve_agent_task` takes, and a proposed action that could not be
    handed straight to it would only be a name the next layer has to undo.
    """
    roster: list[RosterAgent] = []
    if workspace_id:
        roster.extend(
            RosterAgent(name=_spawn_name(agent), capabilities=_capabilities_of(agent))
            for agent in workspace_agents(workspace_id)
        )
    roster.extend(
        RosterAgent(name=_spawn_name(agent), capabilities=_capabilities_of(agent))
        for agent in stores.agents.values()
        if not agent.workspace_id
    )
    return roster


def resolve_agent_task(
    agent_id: str,
    capability: str,
    payload: dict[str, Any],
    *,
    workspace_id: str | None = None,
) -> tuple[str, str, str]:
    """Return `(task_type, description, resolved_agent_id)` for TaskCreate.

    Raises `ValueError` for an agent this workspace's roster does not hold, and
    for a capability that agent does not declare -- the same two refusals
    `build_task_description` made, now asked of the roster rather than of a
    hardcoded tuple.
    """
    agent = resolve_agent(agent_id, workspace_id=workspace_id)
    if agent is None:
        raise ValueError(f"Unknown agent: {agent_id}")
    if capability not in _capabilities_of(agent):
        raise ValueError(f"Capability {capability!r} not valid for {agent_id}")
    name = _spawn_name(agent)
    # The **spawn name**, not the store id. `maistro.agents.pm_runner`'s
    # `_resolve_role` looks the agent up in `_PM_AGENT_TO_ROLE`, which is keyed
    # by bare name; handing it `ws-7.program_manager` misses, and its fallback
    # covers only each role's `PM_PRIMARY_CAPABILITY` -- so `create_epic`,
    # `create_story` and `fetch_program_state` would resolve to no role at all
    # and return a synthetic `source="no_data"` result instead of running.
    #
    # The workspace is not lost by this: the caller passes it to
    # `submit_task(workspace_id=...)`, which is where a Run's scope belongs.
    # Encoding it in the agent id instead would put scope in a field the
    # executor parses as an identity.
    return name, _describe(name, capability, payload), name


def _describe(name: str, capability: str, payload: dict[str, Any]) -> str:
    """The human-readable task description, in `build_task_description`'s shape.

    Kept identical on purpose: this string is what the task list, the audit log
    and the mission feed all show, and changing its shape would read as a
    behaviour change in three surfaces that have nothing to do with #129.
    """
    title = str(payload.get("title", capability.replace("_", " ")))
    summary = str(payload.get("summary", ""))
    program = payload.get("program") or {}
    if isinstance(program, dict) and program.get("program_name") and not title:
        title = str(program["program_name"])
    desc = f"[{name}] {capability}: {title}"
    if summary:
        desc = f"{desc} — {summary}"
    elif isinstance(program, dict) and program.get("summary"):
        desc = f"{desc} — {program['summary']}"
    reason = payload.get("hyperagent_reason")
    if reason:
        desc = f"{desc} (why: {reason})"
    return desc


__all__ = ["pulse_roster", "resolve_agent", "resolve_agent_task"]
