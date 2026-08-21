"""Workspace theme catalog + tone resolution — Persona/Workspace system, Phase D.

Backend-only slice (mirrors Phase C's checklist deferral): the catalog below
matches the static CSS variants already shipped under
`frontend/src/{fantasia-theme.css,themes/dark.css}` plus the unthemed default,
but the actual `document.documentElement.dataset.theme` wiring in
`AppShell.tsx` lands in Phase G alongside the tab bar that would trigger a
switch. `resolve_workspace_tone()` is the dispatch-time resolution point
Phase E's tool-binding resolution will sit next to in `program_hyperagent.py`
— exposed as a pure function so it's unit-testable now, ahead of that wiring.
"""

from __future__ import annotations

from models.workspace import Workspace
from pydantic import BaseModel, ConfigDict

from maistro.personas.schema import PersonaTemplate


class ThemeOption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str


THEME_CATALOG: list[ThemeOption] = [
    ThemeOption(id="default", label="Default"),
    ThemeOption(id="fantasia", label="Fantasia"),
    ThemeOption(id="dark", label="Dark"),
]

_VALID_THEME_IDS = {t.id for t in THEME_CATALOG}


def is_valid_theme_id(theme_id: str) -> bool:
    return theme_id in _VALID_THEME_IDS


def resolve_workspace_tone(workspace: Workspace, persona_template: PersonaTemplate | None) -> str:
    """The tone that should drive this workspace's assembled soul-prompt.

    A workspace's `voice_tone_override`, if set, wins outright; otherwise
    falls back to its persona's declared `voice.tone`; otherwise `""` when no
    persona template resolves (e.g. the persona was deleted/renamed).
    """
    if workspace.voice_tone_override is not None:
        return workspace.voice_tone_override
    if persona_template is not None:
        return persona_template.voice.tone
    return ""
