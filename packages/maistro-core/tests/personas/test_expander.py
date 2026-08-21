"""Persona expander tests — SPEC-192 worked example (P1)."""

from __future__ import annotations

from pathlib import Path

from maistro.agents.recipes import RecipeRegistry
from maistro.agents.spec.agent_spec import AgentRole
from maistro.personas.expander import expand_persona
from maistro.personas.rubric import load_template

FIXTURES = Path(__file__).parent / "fixtures"
PERSONA_YAML = FIXTURES / "plant_wellness_local_seller.yaml"


def test_worked_example_expands_to_three_named_recipes() -> None:
    """SPEC-192 acceptance: plant_wellness_local_seller → 3 named AgentRecipe records."""
    expanded = expand_persona(load_template(PERSONA_YAML))
    assert expanded.persona_id == "plant_wellness_local_seller"
    assert [a.recipe.name for a in expanded.agents] == [
        "plant_wellness_local_seller.caption_writer",
        "plant_wellness_local_seller.care_advisor",
        "plant_wellness_local_seller.local_sales_concierge",
    ]


def test_all_expanded_agents_start_inactive() -> None:
    expanded = expand_persona(load_template(PERSONA_YAML))
    assert all(a.active is False for a in expanded.agents)


def test_hard_gates_wired_on_caption_writer_and_care_advisor() -> None:
    """no_medical_claims must be a hard gate on caption_writer and care_advisor only."""
    expanded = expand_persona(load_template(PERSONA_YAML))
    by_name = {a.recipe.name.rsplit(".", 1)[-1]: a for a in expanded.agents}

    for agent in ("caption_writer", "care_advisor"):
        gates = by_name[agent].hard_gates
        assert [g.criterion for g in gates] == ["no_medical_claims"]
        # The Sentinel payload is the resolved vocabulary check-spec.
        assert gates[0].check["op"] == "keywords_none"
        assert "cure" in gates[0].check["words"]

    assert by_name["local_sales_concierge"].hard_gates == []


def test_recipe_field_mapping() -> None:
    expanded = expand_persona(load_template(PERSONA_YAML))
    caption = expanded.agents[0]
    assert caption.recipe.role == AgentRole.CONVERSATION
    assert caption.recipe.tools == ["draft_post", "schedule_post"]
    assert caption.recipe.description.startswith("On-voice posts")
    assert caption.skills == ["hashtag_suggest"]
    assert caption.scored_by == ["voice_and_safety", "local_commerce"]
    assert caption.reasoning_strategy == "direct"


def test_shared_soul_prompt_from_voice() -> None:
    expanded = expand_persona(load_template(PERSONA_YAML))
    assert expanded.soul_prompt_name == "plant_wellness_local_seller_voice"
    assert "grounding ritual" in expanded.soul_prompt
    assert "porch pickup" in expanded.soul_prompt  # voice.example included
    prompt_names = {a.recipe.prompt_name for a in expanded.agents}
    assert prompt_names == {"plant_wellness_local_seller_voice"}


def test_expansion_registers_recipes_in_registry(tmp_path: Path) -> None:
    registry = RecipeRegistry(recipes_dir=tmp_path)
    expand_persona(load_template(PERSONA_YAML), registry=registry)
    assert registry.get("plant_wellness_local_seller.care_advisor") is not None


def test_expansion_is_idempotent() -> None:
    template = load_template(PERSONA_YAML)
    first = expand_persona(template)
    second = expand_persona(template)
    assert [a.recipe for a in first.agents] == [a.recipe for a in second.agents]
    assert first.soul_prompt == second.soul_prompt


def test_department_kind_expands_to_empty_roster() -> None:
    expanded = expand_persona(load_template(FIXTURES / "gardening_department.yaml"))
    assert expanded.agents == []


def test_workspace_kind_expands_spawns_like_author_creator() -> None:
    """kind: workspace (a workspace-adoptable persona, e.g. PM Fleet) is not
    special-cased like department — it must spawn agents just like author/creator."""
    expanded = expand_persona(load_template(FIXTURES / "pm_fleet_minimal.yaml"))
    assert [a.recipe.name for a in expanded.agents] == [
        "pm_fleet.intake",
        "pm_fleet.program_manager",
    ]
    assert expanded.agents[1].recipe.tools == ["poll_jira", "escalate_issue"]
