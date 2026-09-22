"""Workspace theme catalog + tone resolution — Persona/Workspace system, Phase D.

The catalog is the Workspace design system's persona templates
(ADR-091626-ba4f; `maistro_design/systems/bundled/workspace/manifest.json`
lists them under ``personas.templates``): greenhouse is the default and the
tokens' ``:root``; slate and studio rebind the four persona values. The
frontend applies a workspace's template as ``data-theme`` on ``<html>``;
light/dark is the separate ``data-scheme`` axis, so a theme never forces a
scheme.

Two ids from the hand-written stylesheets this replaced stay *accepted* so
workspaces created before the switchover keep validating: ``fantasia`` and
``dark``. ``canonical_theme_id`` says what each resolves to. They are not in
the catalog, so nothing new is created with them.

`resolve_workspace_tone()` is the dispatch-time resolution point Phase E's
tool-binding resolution sits next to in `program_hyperagent.py` — a pure
function so it is unit-testable ahead of that wiring.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from hive_conductor.models.workspace import Workspace
from maistro.personas.schema import PersonaTemplate


class ThemeOption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str


DEFAULT_THEME_ID = "greenhouse"

THEME_CATALOG: list[ThemeOption] = [
    ThemeOption(id="greenhouse", label="Greenhouse"),
    ThemeOption(id="slate", label="Slate"),
    ThemeOption(id="studio", label="Studio"),
]

#: Ids that are valid to *store* but not offered: the pre-switchover names.
_LEGACY_THEME_IDS: dict[str, str] = {
    "default": "greenhouse",
    "dark": "greenhouse",
    "fantasia": "slate",
}

_VALID_THEME_IDS = {t.id for t in THEME_CATALOG} | set(_LEGACY_THEME_IDS)


def is_valid_theme_id(theme_id: str) -> bool:
    return theme_id in _VALID_THEME_IDS


def canonical_theme_id(theme_id: str) -> str:
    """The catalog template a stored id renders as (legacy ids included)."""
    return _LEGACY_THEME_IDS.get(theme_id, theme_id)


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
