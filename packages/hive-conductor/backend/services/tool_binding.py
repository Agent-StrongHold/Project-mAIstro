"""Sticky per-workspace tool/prompt binding resolution — Persona/Workspace system, Phase E.

Base case: an agent gets its declared `spawns[].tools` straight from the
persona template -- zero extra config needed to "just use the persona as
authored." A workspace's `tool_bindings` (models/workspace.py's
`AgentToolBinding`) is an optional per-agent override: when a binding exists
for an agent, its `tools`/`prompt_fragment` win outright (including an
explicit empty `tools` list, narrowing that agent to zero tools for this one
workspace) -- never touching the shared persona template.

Exposed as pure, dispatch-time-ready functions now, same as Phase D's
`resolve_workspace_tone()`, ahead of `services/program_hyperagent.py` actually
resolving a persona/workspace context to dispatch against (that's Phase H's
dispatch wiring).
"""

from __future__ import annotations

from models.workspace import AgentToolBinding, Workspace

from maistro.personas.schema import PersonaTemplate


def _binding_for_agent(workspace: Workspace, agent_id: str) -> AgentToolBinding | None:
    for binding in workspace.tool_bindings:
        if binding.agent_id == agent_id:
            return binding
    return None


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
