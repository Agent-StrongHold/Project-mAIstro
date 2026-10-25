"""services/tool_binding.py — Persona/Workspace system, Phase E."""

from __future__ import annotations

from datetime import UTC, datetime

from models.workspace import AgentToolBinding, Workspace
from services.tool_binding import resolve_agent_prompt_fragment, resolve_agent_tools


def _workspace(**overrides: object) -> Workspace:
    t = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": "ws-1",
        "persona_template_id": "pm_fleet",
        "name": "PM Fleet",
        "created_at": t,
        "updated_at": t,
    }
    defaults.update(overrides)
    return Workspace(**defaults)


def _persona_with_spawn(agent: str, tools: list[str]):
    from maistro.personas.schema import PersonaTemplate, SpawnSpec

    return PersonaTemplate(id="pm_fleet", spawns=[SpawnSpec(agent=agent, tools=tools)])


def test_resolve_tools_falls_back_to_persona_spawn_when_no_binding() -> None:
    workspace = _workspace(tool_bindings=[])
    persona = _persona_with_spawn("intake", ["create_epic", "poll_jira"])
    assert resolve_agent_tools(workspace, persona, "intake") == ["create_epic", "poll_jira"]


def test_resolve_tools_binding_overrides_persona_defaults() -> None:
    workspace = _workspace(
        tool_bindings=[AgentToolBinding(agent_id="intake", tools=["custom_tool"])]
    )
    persona = _persona_with_spawn("intake", ["create_epic", "poll_jira"])
    assert resolve_agent_tools(workspace, persona, "intake") == ["custom_tool"]


def test_resolve_tools_explicit_empty_binding_narrows_to_zero_tools() -> None:
    """An explicit `tools: []` binding is a deliberate narrowing, not "unset"."""
    workspace = _workspace(tool_bindings=[AgentToolBinding(agent_id="intake", tools=[])])
    persona = _persona_with_spawn("intake", ["create_epic", "poll_jira"])
    assert resolve_agent_tools(workspace, persona, "intake") == []


def test_resolve_tools_is_empty_when_agent_unknown_to_both() -> None:
    workspace = _workspace(tool_bindings=[])
    persona = _persona_with_spawn("intake", ["create_epic"])
    assert resolve_agent_tools(workspace, persona, "some_other_agent") == []


def test_resolve_tools_is_empty_when_no_persona_and_no_binding() -> None:
    workspace = _workspace(tool_bindings=[])
    assert resolve_agent_tools(workspace, None, "intake") == []


def test_resolve_prompt_fragment_empty_when_no_binding() -> None:
    workspace = _workspace(tool_bindings=[])
    assert resolve_agent_prompt_fragment(workspace, "intake") == ""


def test_resolve_prompt_fragment_uses_bindings_fragment() -> None:
    workspace = _workspace(
        tool_bindings=[
            AgentToolBinding(agent_id="intake", prompt_fragment="Always ask for a ticket number.")
        ]
    )
    assert resolve_agent_prompt_fragment(workspace, "intake") == "Always ask for a ticket number."


def test_two_workspaces_on_same_persona_resolve_different_tools() -> None:
    """Phase E's acceptance bar (backend slice): distinct bindings per workspace
    produce distinct resolved tool sets for the same agent/persona."""
    persona = _persona_with_spawn("intake", ["create_epic"])
    ws_a = _workspace(id="ws-a", tool_bindings=[])
    ws_b = _workspace(
        id="ws-b", tool_bindings=[AgentToolBinding(agent_id="intake", tools=["custom_tool"])]
    )
    assert resolve_agent_tools(ws_a, persona, "intake") == ["create_epic"]
    assert resolve_agent_tools(ws_b, persona, "intake") == ["custom_tool"]
