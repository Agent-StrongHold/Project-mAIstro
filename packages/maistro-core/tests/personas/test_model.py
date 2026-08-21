"""Live Persona model tests for ADR-081226-e626."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.personas import Persona, PersonaSurface


def test_persona_is_workspace_owned_taste_style_and_purpose_not_execution_root() -> None:
    persona = Persona(
        id="persona-builders",
        workspace_id="ws-1",
        name="Builders",
        purpose="Build and refine MAIstro workflows",
        taste={"verbosity": "concise"},
        style={"voice": "technical"},
    )

    dumped = persona.model_dump()
    assert dumped["workspace_id"] == "ws-1"
    assert dumped["purpose"] == "Build and refine MAIstro workflows"
    assert dumped["taste"] == {"verbosity": "concise"}
    assert dumped["style"] == {"voice": "technical"}
    assert "run_id" not in dumped
    assert "status" not in dumped
    assert "grants" not in dumped
    assert "denies" not in dumped
    assert "permission_ceiling" not in dumped


def test_persona_exposes_known_and_extension_surfaces_as_configuration() -> None:
    persona = Persona(
        id="persona-builders",
        workspace_id="ws-1",
        name="Builders",
        surfaces={PersonaSurface.UI, PersonaSurface.BUILDERS_CLI, "canvas_book_ui"},
    )

    assert persona.exposes_surface(PersonaSurface.UI)
    assert persona.exposes_surface("builders_cli")
    assert persona.exposes_surface("canvas_book_ui")
    assert not persona.exposes_surface(PersonaSurface.BUILDERS_RSI)


def test_persona_catalogs_and_preferences_are_references() -> None:
    persona = Persona(
        id="persona-builders",
        workspace_id="ws-1",
        name="Builders",
        node_template_ids=["node-template-frank", "node-template-auditor"],
        graph_template_ids=["graph-template-builders"],
        preferred_capability_ids=["capability-github"],
        preferred_binding_ids=["binding-workspace-github"],
        source_template_id="persona-template-builders",
        source_template_version="3",
    )

    assert persona.node_template_ids == ["node-template-frank", "node-template-auditor"]
    assert persona.graph_template_ids == ["graph-template-builders"]
    assert persona.preferred_capability_ids == ["capability-github"]
    assert persona.preferred_binding_ids == ["binding-workspace-github"]
    assert persona.source_template_id == "persona-template-builders"
    assert persona.source_template_version == "3"


def test_persona_preferences_do_not_encode_authority() -> None:
    persona = Persona(
        id="persona-publisher",
        workspace_id="ws-1",
        name="Publisher",
        preferred_binding_ids=["twitter-production"],
        preferred_capability_ids=["social_media_publish"],
    )

    dumped = persona.model_dump()
    assert dumped["preferred_binding_ids"] == ["twitter-production"]
    assert dumped["preferred_capability_ids"] == ["social_media_publish"]
    assert "permissions" not in dumped
    assert "grants" not in dumped
    assert "denies" not in dumped


def test_persona_rejects_legacy_permission_ceiling() -> None:
    with pytest.raises(ValidationError):
        Persona(
            id="persona-legacy",
            workspace_id="ws-1",
            name="Legacy",
            permission_ceiling={"publish"},
        )


def test_persona_defaults_are_explicit_future_object_configuration() -> None:
    persona = Persona(
        id="persona-builders",
        workspace_id="ws-1",
        name="Builders",
        default_model_id="model-sonnet",
        default_provider_id="provider-anthropic",
        behavior_defaults={"approval_style": "review-first"},
        defaults={"temperature": 0.2},
        style_guidance="Prefer concrete implementation language.",
        extension_metadata={"builders": {"show_rsi": True}},
    )

    assert persona.default_model_id == "model-sonnet"
    assert persona.default_provider_id == "provider-anthropic"
    assert persona.behavior_defaults == {"approval_style": "review-first"}
    assert persona.defaults == {"temperature": 0.2}
    assert persona.style_guidance == "Prefer concrete implementation language."


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "", "workspace_id": "ws-1", "name": "Persona"},
        {"id": "p-1", "workspace_id": " ", "name": "Persona"},
        {"id": "p-1", "workspace_id": "ws-1", "name": ""},
        {
            "id": "p-1",
            "workspace_id": "ws-1",
            "name": "Persona",
            "surfaces": {""},
        },
    ],
)
def test_persona_rejects_blank_identity_and_surface_names(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Persona(**kwargs)
