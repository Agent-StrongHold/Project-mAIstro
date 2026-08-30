"""Scorer protocol contract tests (ADR-060).

Pins that every scorer implementation satisfies the Scorer protocol:
  - isinstance check passes
  - score() returns Score with value in [0,1], bool passed, non-empty provider
  - score() never raises on any string input
  - provider attribute is a non-empty string

pytest marker: contract / behavioral
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_TEMPLATES = Path(__file__).resolve().parents[2] / "eval" / "departments" / "yaml"

pytestmark = [pytest.mark.contract("behavioral")]


# ---------------------------------------------------------------------------
# Fixtures — one per scorer implementation
# ---------------------------------------------------------------------------


@pytest.fixture()
def rubric_scorer():
    from eval.loader import load_department
    from eval.scorer import RubricScorer

    return RubricScorer(load_department(_TEMPLATES / "marketing.yaml")[0])


@pytest.fixture()
def deepeval_scorer():
    stub = types.ModuleType("deepeval")
    metrics_mod = types.ModuleType("deepeval.metrics")
    mock_metric = MagicMock()
    mock_metric.score = 0.75
    mock_metric.success = True
    mock_metric.reason = "passes"
    mock_metric.a_measure = AsyncMock(return_value=0.75)
    metrics_mod.GEval = MagicMock(return_value=mock_metric)
    stub.metrics = metrics_mod
    tc_mod = types.ModuleType("deepeval.test_case")
    tc_mod.LLMTestCase = MagicMock(return_value=MagicMock())

    class _ST:
        ACTUAL_OUTPUT = "actual_output"

    tc_mod.SingleTurnParams = _ST
    stub.test_case = tc_mod
    for name, mod in [
        ("deepeval", stub),
        ("deepeval.metrics", metrics_mod),
        ("deepeval.test_case", tc_mod),
    ]:
        sys.modules[name] = mod

    sys.modules.pop("eval.deepeval_scorer", None)
    from eval.deepeval_scorer import DeepEvalScorer

    yield DeepEvalScorer("brand_voice", "Is tone warm?", model="fake")

    for key in list(sys.modules):
        if key == "deepeval" or key.startswith("deepeval."):
            del sys.modules[key]
    sys.modules.pop("eval.deepeval_scorer", None)


@pytest.fixture(params=["rubric_scorer", "deepeval_scorer"])
def any_scorer(request):
    return request.getfixturevalue(request.param)


# ---------------------------------------------------------------------------
# Contract: isinstance — runtime-checkable Protocol
# ---------------------------------------------------------------------------


def test_rubric_scorer_satisfies_protocol(rubric_scorer) -> None:
    try:
        from maistro.protocols.scorer import Scorer

        assert isinstance(rubric_scorer, Scorer), "RubricScorer must satisfy Scorer protocol"
    except ImportError:
        pytest.skip("maistro-core not on PYTHONPATH")


def test_deepeval_scorer_satisfies_protocol(deepeval_scorer) -> None:
    try:
        from maistro.protocols.scorer import Scorer

        assert isinstance(deepeval_scorer, Scorer), "DeepEvalScorer must satisfy Scorer protocol"
    except ImportError:
        pytest.skip("maistro-core not on PYTHONPATH")


# ---------------------------------------------------------------------------
# Contract: provider attribute
# ---------------------------------------------------------------------------


def test_provider_is_non_empty_string(any_scorer) -> None:
    assert isinstance(any_scorer.provider, str)
    assert len(any_scorer.provider) > 0


def test_rubric_provider_name(rubric_scorer) -> None:
    assert rubric_scorer.provider == "rubric"


def test_deepeval_provider_name(deepeval_scorer) -> None:
    assert deepeval_scorer.provider == "deepeval"


# ---------------------------------------------------------------------------
# Contract: score() return shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_returns_value_in_range(any_scorer) -> None:
    result = await any_scorer.score("sample output text")
    assert 0.0 <= result.value <= 1.0, f"value={result.value} out of [0,1]"


@pytest.mark.asyncio
async def test_score_passed_is_bool(any_scorer) -> None:
    result = await any_scorer.score("sample output text")
    assert isinstance(result.passed, bool)


@pytest.mark.asyncio
async def test_score_provider_matches_scorer(any_scorer) -> None:
    result = await any_scorer.score("sample output text")
    assert result.provider == any_scorer.provider


@pytest.mark.asyncio
async def test_score_rationale_is_string(any_scorer) -> None:
    result = await any_scorer.score("sample output text")
    assert isinstance(result.rationale, str)
    assert len(result.rationale) > 0


# ---------------------------------------------------------------------------
# Contract: score() never raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        "",
        " ",
        "normal text",
        "a" * 10_000,
        "unicode: 日本語 العربية русский",
        "emoji 🌿🪴🌱",
        "\n\n\n",
        "\t\t",
    ],
)
async def test_score_never_raises(rubric_scorer, output: str) -> None:
    result = await rubric_scorer.score(output)
    assert result is not None
    assert 0.0 <= result.value <= 1.0


# ---------------------------------------------------------------------------
# Contract: context is always optional
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_accepts_none_context(any_scorer) -> None:
    result = await any_scorer.score("text", context=None)
    assert 0.0 <= result.value <= 1.0


@pytest.mark.asyncio
async def test_score_accepts_empty_context(any_scorer) -> None:
    result = await any_scorer.score("text", context={})
    assert 0.0 <= result.value <= 1.0


@pytest.mark.asyncio
async def test_score_accepts_rich_context(any_scorer) -> None:
    ctx = {"audience": "plant_lovers", "locale": "en-US", "platform": "instagram"}
    result = await any_scorer.score("Water your monstera weekly.", context=ctx)
    assert 0.0 <= result.value <= 1.0
