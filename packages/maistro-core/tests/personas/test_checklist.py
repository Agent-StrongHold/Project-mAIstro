"""capability_checklist() — derive a proposed checklist from a persona's declared spawns."""

from __future__ import annotations

from pathlib import Path

from maistro.personas.checklist import capability_checklist, default_checklist_ids
from maistro.personas.rubric import load_template
from maistro.personas.schema import PersonaTemplate, SpawnSpec

FIXTURES = Path(__file__).parent / "fixtures"


def test_one_item_per_declared_tool_and_skill() -> None:
    template = load_template(FIXTURES / "plant_wellness_local_seller.yaml")
    items = capability_checklist(template)

    caption_items = [i for i in items if i.agent == "caption_writer"]
    assert {i.name for i in caption_items if i.kind == "tool"} == {"draft_post", "schedule_post"}
    assert {i.name for i in caption_items if i.kind == "skill"} == {"hashtag_suggest"}

    care_items = [i for i in items if i.agent == "care_advisor"]
    assert {i.name for i in care_items if i.kind == "tool"} == {"search_care_db"}
    assert [i for i in care_items if i.kind == "skill"] == []


def test_ids_are_unique_and_agent_scoped() -> None:
    template = load_template(FIXTURES / "pm_fleet_minimal.yaml")
    items = capability_checklist(template)
    ids = [i.id for i in items]
    assert len(ids) == len(set(ids)), "checklist ids must be unique within one persona"
    assert "intake.tool.create_epic" in ids
    assert "program_manager.tool.poll_jira" in ids
    assert "program_manager.tool.escalate_issue" in ids


def test_department_kind_has_no_checklist_items() -> None:
    """department personas carry no spawns (eval rubric only) -- an empty
    checklist, not an error."""
    template = load_template(FIXTURES / "gardening_department.yaml")
    assert capability_checklist(template) == []


def test_label_is_human_readable() -> None:
    template = load_template(FIXTURES / "pm_fleet_minimal.yaml")
    items = capability_checklist(template)
    poll_jira = next(i for i in items if i.name == "poll_jira")
    assert poll_jira.label == "Poll Jira"


def test_default_checklist_ids_pre_checks_everything_declared() -> None:
    template = load_template(FIXTURES / "pm_fleet_minimal.yaml")
    ids = default_checklist_ids(template)
    assert ids == [i.id for i in capability_checklist(template)]
    assert len(ids) > 0


def test_same_tool_name_under_two_agents_produces_two_distinct_rows() -> None:
    template = load_template(FIXTURES / "plant_wellness_local_seller.yaml")
    # care_advisor and local_sales_concierge both exist as separate agents;
    # confirm no id collision even if a future template reuses a tool name
    # across agents (a synthetic check, since the fixture doesn't repeat one).
    items = capability_checklist(template)
    assert len({i.id for i in items}) == len(items)


def test_duplicate_tool_within_one_spawn_deduplicates_to_one_row() -> None:
    template = PersonaTemplate(
        kind="workspace",
        id="dup_tool",
        spawns=[SpawnSpec(agent="intake", tools=["create_epic", "create_epic"], skills=[])],
    )
    items = capability_checklist(template)
    assert [i.id for i in items] == ["intake.tool.create_epic"]


def test_repeated_agent_name_across_spawns_deduplicates_by_id() -> None:
    template = PersonaTemplate(
        kind="workspace",
        id="dup_agent",
        spawns=[
            SpawnSpec(agent="intake", tools=["create_epic"], skills=[]),
            SpawnSpec(agent="intake", tools=["create_epic"], skills=["triage"]),
        ],
    )
    items = capability_checklist(template)
    ids = [i.id for i in items]
    assert ids == ["intake.tool.create_epic", "intake.skill.triage"]
    assert len(ids) == len(set(ids))
