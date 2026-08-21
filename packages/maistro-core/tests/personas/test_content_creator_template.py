"""The real content_creator.yaml seed persona -- second real kind: workspace
persona (after pm_fleet.yaml), authored for the persona-picker slice. Mirrors
test_pm_fleet_template.py's pattern.
"""

from __future__ import annotations

from maistro.personas.checklist import capability_checklist, default_checklist_ids
from maistro.personas.expander import expand_persona
from maistro.personas.rubric import load_templates

CONTENT_CREATOR_AGENTS = {"ideation", "scheduler", "analytics"}


def _content_creator():
    templates = load_templates()
    assert "content_creator" in templates, "personas/templates/content_creator.yaml failed to load"
    return templates["content_creator"]


def test_loads_via_the_default_templates_directory() -> None:
    template = _content_creator()
    assert template.kind == "workspace"
    assert template.id == "content_creator"


def test_brand_and_ui_scope_are_distinct_from_pm_fleet() -> None:
    template = _content_creator()
    assert template.brand.display_name == "Content Studio"
    assert template.ui_scope == ["Drafts", "Schedule", "Analytics"]


def test_spawns_cover_every_content_creator_agent() -> None:
    template = _content_creator()
    assert {spawn.agent for spawn in template.spawns} == CONTENT_CREATOR_AGENTS


def test_checklist_has_unique_ids() -> None:
    template = _content_creator()
    items = capability_checklist(template)
    ids = [i.id for i in items]
    assert len(ids) == len(set(ids))
    assert default_checklist_ids(template) == ids


def test_expands_to_three_inactive_agent_recipes() -> None:
    template = _content_creator()
    expanded = expand_persona(template)
    assert expanded.persona_id == "content_creator"
    names = {agent.recipe.name for agent in expanded.agents}
    assert names == {f"content_creator.{agent}" for agent in CONTENT_CREATOR_AGENTS}
    assert all(agent.active is False for agent in expanded.agents)
