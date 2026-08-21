"""Writable persona-template authoring — Persona/Workspace system, PersonaWizard.

Every persona today is a hand-authored YAML file under
`maistro.personas.rubric.DEFAULT_TEMPLATES_DIR` (packaged inside maistro-core).
That's fine for personas that ship with the product, but a user building
their own persona in-app has nowhere to write one — `load_templates()` and
`PersonaTemplate` are read-only. This module adds a second, writable
templates directory under this deployment's `CONDUCTOR_DATA_DIR` (not the
installed package), and merges it with the built-in directory wherever a
caller resolves "every available persona template" — so a wizard-authored
persona shows up in the persona picker, checklist, etc. with zero changes
to those call sites.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from config import get_settings

from maistro.personas.rubric import load_templates
from maistro.personas.schema import (
    BrandSpec,
    InterviewQuestionSpec,
    PersonaTemplate,
    SpawnSpec,
    VoiceSpec,
)

# Filename-safe and matches the id patterns already used by shipped personas
# (pm_fleet, content_creator) — enforced here rather than left to the
# filesystem, since `id` becomes a YAML filename below.
PERSONA_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class PersonaTemplateIdConflict(ValueError):
    """Raised when a to-be-created persona template's id already exists,
    whether as a built-in template or a previously wizard-authored one."""


def user_templates_dir() -> Path:
    return Path(get_settings().conductor_data_dir).expanduser() / "persona_templates"


def all_persona_templates() -> dict[str, PersonaTemplate]:
    """Built-in templates plus this deployment's wizard-authored ones.

    Both share one id namespace; on collision the built-in wins, since a
    user-authored persona must not be able to silently shadow a shipped one
    (e.g. redefining "pm_fleet") — `create_persona_template` already refuses
    to create that conflict in the first place, this is just the read-side
    tie-break for templates that predate that check or were placed by hand.
    """
    custom = load_templates(directory=user_templates_dir())
    builtin = load_templates()
    return {**custom, **builtin}


def create_persona_template(
    *,
    id: str,
    display_name: str,
    tagline: str,
    archetype: str,
    audience: str,
    tone: str,
    ui_scope: list[str],
    spawns: list[SpawnSpec],
    interview: list[InterviewQuestionSpec] | None = None,
) -> PersonaTemplate:
    """Validate and persist a new, wizard-authored `kind: workspace` persona
    template as a YAML file, exactly like a hand-authored one — so every
    existing reader (`load_templates()`, the persona picker, the checklist
    route) picks it up with no changes on its side. `interview` (optional)
    is this persona's own onboarding interview script -- omitted or empty
    means "no custom script", and routes/program.py falls back to the
    generic one, same as any hand-authored persona that never declared
    `interview:` in its YAML."""
    if not PERSONA_ID_PATTERN.fullmatch(id):
        raise ValueError(
            "id must start with a lowercase letter and contain only lowercase "
            "letters, digits, and underscores"
        )
    if id in all_persona_templates():
        raise PersonaTemplateIdConflict(f"a persona template with id {id!r} already exists")

    template = PersonaTemplate(
        kind="workspace",
        id=id,
        brand=BrandSpec(display_name=display_name, tagline=tagline),
        voice=VoiceSpec(archetype=archetype, audience=audience, tone=tone),
        ui_scope=ui_scope,
        spawns=spawns,
        interview=interview or [],
    )

    directory = user_templates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{id}.yaml"
    path.write_text(
        yaml.safe_dump(template.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return template
