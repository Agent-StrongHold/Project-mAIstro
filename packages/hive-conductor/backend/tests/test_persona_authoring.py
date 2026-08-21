"""services/persona_authoring.py -- Persona/Workspace system, PersonaWizard.

A wizard-authored persona is a real YAML file, written to a per-deployment
directory distinct from the packaged built-ins, and immediately resolvable
through the exact same all_persona_templates() every other reader uses.
"""

from __future__ import annotations

import pytest
from services.persona_authoring import (
    PersonaTemplateIdConflict,
    all_persona_templates,
    create_persona_template,
    user_templates_dir,
)

from maistro.personas.rubric import load_templates
from maistro.personas.schema import InterviewQuestionSpec, SpawnSpec


def _spawn() -> list[SpawnSpec]:
    return [SpawnSpec(agent="host", role="Greets guests", tools=["send_message"], skills=[])]


def test_creates_a_yaml_file_resolvable_via_load_templates(tmp_path) -> None:
    from services import persona_authoring

    template = create_persona_template(
        id="dinner_party",
        display_name="Dinner Party",
        tagline="Plan the night",
        archetype="a gracious host",
        audience="small groups",
        tone="warm",
        ui_scope=["Guests", "Menu"],
        spawns=_spawn(),
    )
    assert template.id == "dinner_party"
    assert template.kind == "workspace"

    on_disk = load_templates(directory=persona_authoring.user_templates_dir())
    assert "dinner_party" in on_disk
    assert on_disk["dinner_party"].brand.display_name == "Dinner Party"
    assert on_disk["dinner_party"].spawns[0].agent == "host"


def test_resolves_through_all_persona_templates() -> None:
    create_persona_template(
        id="book_club",
        display_name="Book Club",
        tagline="",
        archetype="",
        audience="",
        tone="",
        ui_scope=[],
        spawns=_spawn(),
    )
    assert "book_club" in all_persona_templates()


def test_rejects_id_colliding_with_a_builtin_template() -> None:
    with pytest.raises(PersonaTemplateIdConflict):
        create_persona_template(
            id="pm_fleet",
            display_name="Not The Real One",
            tagline="",
            archetype="",
            audience="",
            tone="",
            ui_scope=[],
            spawns=_spawn(),
        )


def test_rejects_id_colliding_with_a_previously_authored_template() -> None:
    create_persona_template(
        id="once",
        display_name="First",
        tagline="",
        archetype="",
        audience="",
        tone="",
        ui_scope=[],
        spawns=_spawn(),
    )
    with pytest.raises(PersonaTemplateIdConflict):
        create_persona_template(
            id="once",
            display_name="Second",
            tagline="",
            archetype="",
            audience="",
            tone="",
            ui_scope=[],
            spawns=_spawn(),
        )


@pytest.mark.parametrize("bad_id", ["Bad-Id", "1starts_with_digit", "has space", ""])
def test_rejects_invalid_id_formats(bad_id: str) -> None:
    with pytest.raises(ValueError):
        create_persona_template(
            id=bad_id,
            display_name="Whatever",
            tagline="",
            archetype="",
            audience="",
            tone="",
            ui_scope=[],
            spawns=_spawn(),
        )


def test_interview_defaults_to_no_custom_script() -> None:
    template = create_persona_template(
        id="no_interview",
        display_name="No Interview",
        tagline="",
        archetype="",
        audience="",
        tone="",
        ui_scope=[],
        spawns=_spawn(),
    )
    assert template.interview == []


def test_interview_script_is_persisted_and_resolvable() -> None:
    from services import persona_authoring

    template = create_persona_template(
        id="dinner_party_with_interview",
        display_name="Dinner Party",
        tagline="",
        archetype="",
        audience="",
        tone="",
        ui_scope=[],
        spawns=_spawn(),
        interview=[
            InterviewQuestionSpec(
                field="program_name", agent="host", question="What's the occasion?"
            ),
            InterviewQuestionSpec(field="vibe", question="What vibe are we going for?"),
        ],
    )
    assert [q.field for q in template.interview] == ["program_name", "vibe"]

    on_disk = load_templates(directory=persona_authoring.user_templates_dir())
    resolved = on_disk["dinner_party_with_interview"]
    assert resolved.interview[0].question == "What's the occasion?"
    assert resolved.interview[1].agent == "intake"  # default, round-trips through YAML


def test_user_templates_dir_is_under_conductor_data_dir(monkeypatch, tmp_path) -> None:
    """Exercises the real (unpatched) function -- `user_templates_dir` was
    bound into this test module's namespace at import time, so this
    reference is unaffected by conftest's autouse patch on the source
    module's attribute (which only redirects lookups made from inside
    persona_authoring.py itself, e.g. create_persona_template's)."""
    from config import get_settings

    monkeypatch.setenv("CONDUCTOR_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        assert user_templates_dir() == tmp_path / "persona_templates"
    finally:
        get_settings.cache_clear()
