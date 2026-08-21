"""RubricScorer / DeepEvalScorer adapter tests (SPEC-192 P0/P1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.personas.rubric import load_evals
from maistro.personas.scorer import (
    DeepEvalScorer,
    RubricScorer,
    create_judge_scorer,
    deepeval_available,
)
from maistro.protocols.scorer import Score, Scorer

FIXTURES = Path(__file__).parent / "fixtures"
PERSONA_YAML = FIXTURES / "plant_wellness_local_seller.yaml"


def _rubric_scorer() -> RubricScorer:
    return RubricScorer(load_evals(PERSONA_YAML)[0])


def test_rubric_scorer_satisfies_protocol() -> None:
    assert isinstance(_rubric_scorer(), Scorer)


async def test_rubric_scorer_scores() -> None:
    scorer = _rubric_scorer()
    score = await scorer.score("A grounding watering routine — a small win. Pet-safe and calm.")
    assert isinstance(score, Score)
    assert score.provider == "rubric"
    assert 0.0 <= score.value <= 1.0
    assert score.passed is (score.value >= 0.5)
    assert "wellness_framing" in score.evidence


async def test_rubric_scorer_never_raises() -> None:
    """Scorer contract: bad rubric input yields value=0, not an exception."""
    from maistro.personas.rubric import RubricEval
    from maistro.personas.schema import CriterionSpec, EvalSpec

    broken = RubricEval(
        "x",
        EvalSpec(
            name="broken", criteria=[CriterionSpec(name="c", weight=1, check={"op": "bogus"})]
        ),
    )
    score = await RubricScorer(broken).score("anything")
    assert score.value == 0.0
    assert score.passed is False
    assert "failed" in score.rationale


def test_rubric_scorer_from_yaml() -> None:
    scorer = RubricScorer.from_yaml(str(PERSONA_YAML), eval_index=1)
    assert scorer.eval_name == "local_commerce"


def test_deepeval_is_absent_here() -> None:
    """This environment intentionally has no deepeval installed."""
    assert deepeval_available() is False


def test_deepeval_scorer_raises_import_error_when_absent() -> None:
    if deepeval_available():
        pytest.skip("deepeval installed; construction path covered elsewhere")
    with pytest.raises(ImportError, match="deepeval is not installed"):
        DeepEvalScorer("voice", "warm and safe", model="some-judge-model")


def test_create_judge_scorer_falls_back_gracefully() -> None:
    """SPEC-192 acceptance: no deepeval → RubricScorer fallback, no import error."""
    fallback = _rubric_scorer()
    scorer = create_judge_scorer("voice", "warm and safe", fallback=fallback, model="judge")
    if deepeval_available():
        assert isinstance(scorer, DeepEvalScorer)
    else:
        assert scorer is fallback


def test_create_judge_scorer_without_model_uses_fallback() -> None:
    fallback = _rubric_scorer()
    assert create_judge_scorer("voice", "criteria", fallback=fallback) is fallback


def test_personas_package_imports_without_deepeval() -> None:
    """Importing the package never requires deepeval (graceful degradation)."""
    import maistro.personas as personas

    assert hasattr(personas, "DeepEvalScorer")
