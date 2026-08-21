"""Generic RubricEval loader tests (SPEC-192 P0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.personas.rubric import load_evals, load_template, load_templates

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
