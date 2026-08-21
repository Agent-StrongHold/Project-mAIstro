"""services/themes.py — Persona/Workspace system, Phase D."""

from __future__ import annotations

from datetime import UTC, datetime

from models.workspace import Workspace
from services.themes import THEME_CATALOG, is_valid_theme_id, resolve_workspace_tone


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


def test_theme_catalog_includes_default_fantasia_and_dark() -> None:
    ids = {t.id for t in THEME_CATALOG}
    assert ids == {"default", "fantasia", "dark"}


def test_is_valid_theme_id() -> None:
    assert is_valid_theme_id("fantasia") is True
    assert is_valid_theme_id("nope") is False


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
