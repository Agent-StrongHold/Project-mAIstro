"""services/themes.py — Persona/Workspace system, Phase D."""

from __future__ import annotations

from datetime import UTC, datetime

from models.workspace import Workspace
from services.themes import (
    DEFAULT_THEME_ID,
    THEME_CATALOG,
    canonical_theme_id,
    is_valid_theme_id,
    resolve_workspace_tone,
)


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


def test_theme_catalog_is_the_workspace_persona_templates() -> None:
    """The catalog is what the bundled Workspace design system offers as
    persona templates, greenhouse first; nothing is invented here."""
    import json
    from pathlib import Path

    manifest = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "maistro-design/src/maistro_design/systems/bundled/workspace/manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert [t.id for t in THEME_CATALOG] == manifest["personas"]["templates"]
    assert manifest["personas"]["default"] == DEFAULT_THEME_ID


def test_is_valid_theme_id() -> None:
    assert is_valid_theme_id("slate") is True
    assert is_valid_theme_id("nope") is False


def test_retired_ids_stay_valid_and_resolve_to_a_template() -> None:
    """Workspaces stored before the switchover carry "default", "dark" or
    "fantasia"; they keep validating and render as the nearest template
    without a migration, but they are not in the catalog."""
    catalog = {t.id for t in THEME_CATALOG}
    for legacy, template in (("default", "greenhouse"), ("dark", "greenhouse"), ("fantasia", "slate")):
        assert is_valid_theme_id(legacy) is True
        assert legacy not in catalog
        assert canonical_theme_id(legacy) == template
    assert canonical_theme_id("studio") == "studio"


def test_resolve_tone_uses_override_when_set() -> None:
    workspace = _workspace(voice_tone_override="playful and terse")
    from maistro.personas.schema import PersonaTemplate, VoiceSpec

    template = PersonaTemplate(id="pm_fleet", voice=VoiceSpec(tone="formal"))
    assert resolve_workspace_tone(workspace, template) == "playful and terse"


def test_resolve_tone_falls_back_to_persona_voice_when_no_override() -> None:
    workspace = _workspace(voice_tone_override=None)
    from maistro.personas.schema import PersonaTemplate, VoiceSpec

    template = PersonaTemplate(id="pm_fleet", voice=VoiceSpec(tone="formal"))
    assert resolve_workspace_tone(workspace, template) == "formal"


def test_resolve_tone_is_empty_when_no_override_and_no_persona() -> None:
    workspace = _workspace(voice_tone_override=None)
    assert resolve_workspace_tone(workspace, None) == ""


def test_empty_string_override_is_honored_not_treated_as_unset() -> None:
    """An explicit '' override (user cleared the field) wins over the persona's
    tone -- only `None` means "no override"."""
    workspace = _workspace(voice_tone_override="")
    from maistro.personas.schema import PersonaTemplate, VoiceSpec

    template = PersonaTemplate(id="pm_fleet", voice=VoiceSpec(tone="formal"))
    assert resolve_workspace_tone(workspace, template) == ""
