"""Generic RubricEval loader tests (SPEC-192 P0)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import maistro.personas.rubric as rubric_module
from maistro.personas.rubric import (
    LEGACY_DEPARTMENT_YAML,
    PERSONA_TEMPLATE_YAML,
    load_evals,
    load_template,
    load_templates,
)

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY_DEPT_YAML = (
    Path(__file__).parents[3]
    / "hive-conductor"
    / "eval"
    / "departments"
    / "yaml"
    / "marketing.yaml"
)


async def test_load_persona_template_evals() -> None:
    evals = load_evals(FIXTURES / "plant_wellness_local_seller.yaml")
    assert [e.eval_name for e in evals] == ["voice_and_safety", "local_commerce"]
    assert all(e.department == "plant_wellness_local_seller" for e in evals)

    good = (
        "Watering my monstera is my grounding routine — a small win. "
        "Pet-safe pothos ready for porch pickup this weekend, DM to order. $15. "
        "What plant helps you breathe?"
    )
    result = await evals[0].score(good)
    assert result.score == 100

    bad = "This plant cures anxiety, guaranteed to fix everything pharmacologically."
    result = await evals[0].score(bad)
    assert result.score < 50
    by_name = {c["name"]: c["passed"] for c in result.details["criteria"]}
    assert by_name["no_medical_claims"] is False


async def test_new_domain_via_single_yaml_file_no_python() -> None:
    """SPEC-192 acceptance: a new domain is one YAML file, no Python changes."""
    evals = load_evals(FIXTURES / "gardening_department.yaml")
    assert evals[0].department == "gardening"
    result = await evals[0].score("Water deeply, then mulch.")
    assert result.score == 100


def test_load_templates_directory_kind_discrimination() -> None:
    templates = load_templates(FIXTURES)
    assert templates["gardening"].kind == "department"
    assert templates["plant_wellness_local_seller"].kind == "creator"


def test_native_template_records_loader_attested_source() -> None:
    path = FIXTURES / "plant_wellness_local_seller.yaml"

    template = load_template(path)

    assert template.source_provenance is not None
    assert template.source_provenance.source_format == PERSONA_TEMPLATE_YAML
    assert template.source_provenance.source_locator == str(path)


def test_loader_refuses_incomplete_source_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "template.yaml"
    path.write_text("kind: creator\nid: incomplete\n", encoding="utf-8")
    monkeypatch.setattr(
        rubric_module,
        "PersonaTemplateSource",
        lambda **_: SimpleNamespace(source_format="", source_locator=""),
    )

    with pytest.raises(RuntimeError, match="source attestation is incomplete"):
        rubric_module.load_template(path)


def test_loader_refuses_when_model_drops_attested_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "template.yaml"
    path.write_text("kind: creator\nid: dropped\n", encoding="utf-8")

    class DroppingPersonaTemplate:
        def __init__(self, **_: object) -> None:
            pass

        def model_copy(self, *, update: dict[str, object]) -> SimpleNamespace:
            assert "source_provenance" in update
            return SimpleNamespace(source_provenance=None)

    monkeypatch.setattr(rubric_module, "PersonaTemplate", DroppingPersonaTemplate)

    with pytest.raises(RuntimeError, match="source attestation was not retained"):
        rubric_module.load_template(path)


@pytest.mark.skipif(not LEGACY_DEPT_YAML.exists(), reason="hive-conductor not checked out")
def test_legacy_shape_survives_normalization_as_source_provenance() -> None:
    template = load_template(LEGACY_DEPT_YAML)

    assert template.kind == "department"
    assert template.id == "marketing"
    assert template.source_provenance is not None
    assert template.source_provenance.source_format == LEGACY_DEPARTMENT_YAML
    assert template.source_provenance.source_locator == str(LEGACY_DEPT_YAML)


def test_source_cannot_self_assert_provenance(tmp_path: Path) -> None:
    path = tmp_path / "claimed.yaml"
    path.write_text(
        "kind: creator\nid: claimed\nsource_provenance: totally-not-a-valid-object\n",
        encoding="utf-8",
    )

    template = load_template(path)

    assert template.source_provenance is not None
    assert template.source_provenance.source_format == PERSONA_TEMPLATE_YAML
    assert template.source_provenance.source_locator == str(path)


def test_source_provenance_is_not_copied_into_exported_template_content() -> None:
    template = load_template(FIXTURES / "plant_wellness_local_seller.yaml")

    assert "source_provenance" not in template.model_dump(mode="json")


def test_load_templates_missing_dir_is_empty() -> None:
    assert load_templates(FIXTURES / "does-not-exist") == {}


@pytest.mark.skipif(not LEGACY_DEPT_YAML.exists(), reason="hive-conductor not checked out")
async def test_legacy_department_yaml_shape_loads() -> None:
    """Behavior-preserving: the migrated hive-conductor department YAML loads as-is."""
    template = load_template(LEGACY_DEPT_YAML)
    assert template.kind == "department"
    assert template.id == "marketing"
    evals = load_evals(LEGACY_DEPT_YAML)
    assert {e.eval_name for e in evals} >= {"brand_voice", "cta_clarity"}
    result = await evals[0].score("Our trusted, innovative platform. Sign up today!")
    assert 0 <= result.score <= 100


def test_invalid_binding_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "kind: creator\nid: bad\nevals: []\nspawns:\n  - agent: a\n    scored_by: [nope]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown evals"):
        load_template(bad)
