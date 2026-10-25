"""Sticky per-workspace tool/prompt binding resolution — Persona/Workspace system.

Base case: an agent gets its declared `spawns[].tools` straight from the
persona template -- zero extra config needed to "just use the persona as
authored." A workspace's `tool_bindings` (models/workspace.py's
`AgentToolBinding`) is an optional per-agent override: when a binding exists
for an agent, its `tools`/`prompt_fragment` win outright (including an
explicit empty `tools` list, narrowing that agent to zero tools for this one
workspace) -- never touching the shared persona template.

Dispatch (#2276 / conductor-412) consults these resolvers at the agent gate
(`agent_invocation`) and runtime materialization (`_build_runtime_agent`).
"""

from __future__ import annotations

from models.workspace import AgentToolBinding, Workspace

from maistro.personas.schema import PersonaTemplate


def _binding_for_agent(workspace: Workspace, agent_id: str) -> AgentToolBinding | None:
    for binding in workspace.tool_bindings:
        if binding.agent_id == agent_id:
            return binding
    return None


def binding_tools_override(workspace_id: str | None, agent_id: str) -> list[str] | None:
    """Workspace binding tools for ``agent_id``, or ``None`` when unset.

    ``None`` means "no sticky binding — use persona/materialized capabilities."
    A list (including ``[]``) means the binding wins outright at dispatch.
    Reads the Hive presentation store synchronously so the sync agent gate can
    honor bindings without awaiting Workspace identity.
    """
    if not workspace_id:
        return None
    from services.workspace_authority import presentation_store

    presentation = presentation_store().get(workspace_id)
    if presentation is None:
        return None
    for binding in presentation.tool_bindings:
        if binding.agent_id == agent_id:
            return list(binding.tools)
    return None


def binding_prompt_fragment(workspace_id: str | None, agent_id: str) -> str:
    """Sticky prompt fragment for ``agent_id`` in this Workspace, or ``\"\"``."""
    if not workspace_id:
        return ""
    from services.workspace_authority import presentation_store

    presentation = presentation_store().get(workspace_id)
    if presentation is None:
        return ""
    for binding in presentation.tool_bindings:
        if binding.agent_id == agent_id:
            return binding.prompt_fragment
    return ""


def resolve_agent_tools(
    workspace: Workspace, persona_template: PersonaTemplate | None, agent_id: str
) -> list[str]:
    """The tool list one agent should dispatch with in this workspace.

    A sticky binding for this agent wins outright when one exists (even an
    explicit `tools: []`, narrowing to zero); otherwise falls back to the
    persona's declared `spawns[].tools` for that agent; otherwise `[]` when
    neither the workspace nor the persona says anything about this agent.
    """
    binding = _binding_for_agent(workspace, agent_id)
    if binding is not None:
        return list(binding.tools)
    if persona_template is not None:
        for spawn in persona_template.spawns:
            if spawn.agent == agent_id:
                return list(spawn.tools)
    return []


def resolve_agent_prompt_fragment(workspace: Workspace, agent_id: str) -> str:
    """The workspace-specific prompt fragment to append for one agent.

    Empty when the workspace declares no sticky binding for this agent, or
    the binding declares no fragment -- this is purely additive, layered on
    top of the persona's own role prompt, never a replacement for it.
    """
    binding = _binding_for_agent(workspace, agent_id)
    return binding.prompt_fragment if binding is not None else ""
