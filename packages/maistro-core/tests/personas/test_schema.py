"""PersonaTemplate schema tests — kind: workspace + brand/ui_scope (persona/workspace system)."""

from __future__ import annotations

from pathlib import Path

from maistro.personas.rubric import load_template
from maistro.personas.schema import BrandSpec, InterviewQuestionSpec, PersonaTemplate

FIXTURES = Path(__file__).parent / "fixtures"


def test_workspace_kind_is_a_valid_discriminator() -> None:
    template = PersonaTemplate(kind="workspace", id="x")
    assert template.kind == "workspace"


def test_brand_and_ui_scope_default_empty() -> None:
    template = PersonaTemplate(kind="department", id="x")
    assert template.brand == BrandSpec()
    assert template.ui_scope == []


def test_interview_defaults_empty() -> None:
    template = PersonaTemplate(kind="workspace", id="x")
    assert template.interview == []


def test_interview_accepts_a_custom_question_script() -> None:
    template = PersonaTemplate(
        kind="workspace",
        id="dinner_party",
        interview=[
            {"field": "program_name", "agent": "host", "question": "What's the occasion?"},
            {"field": "vibe", "question": "What vibe are we going for?"},
        ],
    )
    assert template.interview == [
        InterviewQuestionSpec(field="program_name", agent="host", question="What's the occasion?"),
        InterviewQuestionSpec(field="vibe", agent="intake", question="What vibe are we going for?"),
    ]


def test_loads_workspace_template_with_brand_and_ui_scope() -> None:
    template = load_template(FIXTURES / "pm_fleet_minimal.yaml")
    assert template.kind == "workspace"
    assert template.brand.display_name == "PM Fleet"
    assert template.brand.icon == "🐝"
    assert template.ui_scope == [
        "program",
        "missions",
        "integrations",
        "work_items",
        "credentials",
    ]
    assert [s.agent for s in template.spawns] == ["intake", "program_manager"]
