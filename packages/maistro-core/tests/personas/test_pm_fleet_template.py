"""The real pm_fleet.yaml seed persona -- Persona/Workspace system, Phase H.

Unlike test_checklist.py's pm_fleet_minimal.yaml fixture (a deliberately
tiny 2-agent stub for schema/expander tests), this loads the actual shipped
template under personas/templates/, the one `load_templates()` (used by
`GET /v1/workspaces/persona-templates/{id}/checklist`) resolves at runtime.
"""

from __future__ import annotations

from maistro.personas.checklist import capability_checklist, default_checklist_ids
from maistro.personas.expander import expand_persona
from maistro.personas.rubric import load_templates

PM_FLEET_AGENTS = {
    "intake",
    "program_manager",
    "research",
    "delivery",
    "risk_dependency",
    "reporting",
}


def _pm_fleet():
    templates = load_templates()
    assert "pm_fleet" in templates, "personas/templates/pm_fleet.yaml failed to load"
    return templates["pm_fleet"]


def test_loads_via_the_default_templates_directory() -> None:
    template = _pm_fleet()
    assert template.kind == "workspace"
    assert template.id == "pm_fleet"


def test_brand_and_ui_scope_match_pmbranding_ts_verbatim() -> None:
    template = _pm_fleet()
    assert template.brand.display_name == "PM Fleet"
    assert template.brand.tagline == (
        "Program hyperagent — interview, autonomous polls, gated Jira creates"
    )
    assert template.ui_scope == [
        "Program",
        "Activity",
        "Integrations",
        "Jira drafts",
        "Credentials",
    ]


def test_spawns_cover_every_pm_fleet_agent() -> None:
    template = _pm_fleet()
    assert {spawn.agent for spawn in template.spawns} == PM_FLEET_AGENTS


def test_checklist_has_unique_ids_across_all_six_agents() -> None:
    """program_manager and research both declare fetch_program_state -- a real
    cross-agent duplicate this persona actually has, unlike the synthetic case
    in test_checklist.py. Confirms the Phase C dedupe fix holds on real data."""
    template = _pm_fleet()
    items = capability_checklist(template)
    ids = [i.id for i in items]
    assert len(ids) == len(set(ids))
    assert "program_manager.skill.fetch_program_state" in ids
    assert "research.skill.fetch_program_state" in ids
    assert default_checklist_ids(template) == ids


def test_expands_to_six_inactive_agent_recipes() -> None:
    template = _pm_fleet()
    expanded = expand_persona(template)
    assert expanded.persona_id == "pm_fleet"
    names = {agent.recipe.name for agent in expanded.agents}
    assert names == {f"pm_fleet.{agent}" for agent in PM_FLEET_AGENTS}
    assert all(agent.active is False for agent in expanded.agents)
