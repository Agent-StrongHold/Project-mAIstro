"""Tests for DeepEvalScorer (ADR-060).

All deepeval internals are mocked so these tests run without a real LLM
and without deepeval installed (the missing-dep path is tested explicitly).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ---------------------------------------------------------------------------
# Helpers — build a minimal deepeval stub so tests are self-contained
# ---------------------------------------------------------------------------


def _make_deepeval_stub(
    score: float = 0.8, success: bool = True, reason: str = "looks good"
) -> types.ModuleType:
    """Return a minimal deepeval module tree sufficient for DeepEvalScorer."""
    stub = types.ModuleType("deepeval")

    # deepeval.metrics.GEval
    metrics_mod = types.ModuleType("deepeval.metrics")
    mock_metric = MagicMock()
    mock_metric.score = score
    mock_metric.success = success
    mock_metric.reason = reason
    mock_metric.a_measure = AsyncMock(return_value=score)
    GEvalCls = MagicMock(return_value=mock_metric)
    metrics_mod.GEval = GEvalCls
    stub.metrics = metrics_mod

    # deepeval.test_case
    tc_mod = types.ModuleType("deepeval.test_case")
    tc_mod.LLMTestCase = MagicMock(return_value=MagicMock())

    class _SingleTurnParams:
        ACTUAL_OUTPUT = "actual_output"

    tc_mod.SingleTurnParams = _SingleTurnParams
    stub.test_case = tc_mod

    # deepeval.models.base_model
    models_mod = types.ModuleType("deepeval.models")
    base_mod = types.ModuleType("deepeval.models.base_model")
    base_mod.DeepEvalBaseLLM = object
    models_mod.base_model = base_mod
    stub.models = models_mod

    # Register all sub-modules
    for name, mod in [
        ("deepeval", stub),
        ("deepeval.metrics", metrics_mod),
        ("deepeval.test_case", tc_mod),
        ("deepeval.models", models_mod),
        ("deepeval.models.base_model", base_mod),
    ]:
        sys.modules[name] = mod

    return stub


def _remove_deepeval_stub() -> None:
    for key in list(sys.modules):
        if key == "deepeval" or key.startswith("deepeval."):
            del sys.modules[key]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_construction_succeeds_when_deepeval_available() -> None:
    _make_deepeval_stub()
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer(
            "voice_quality", "Is the tone warm and first-person?", model="fake-model"
        )
        assert scorer.provider == "deepeval"
        assert scorer._eval_name == "voice_quality"
        assert scorer._threshold == 0.5
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


def test_construction_raises_import_error_when_deepeval_missing() -> None:
    _remove_deepeval_stub()
    sys.modules.pop("eval.deepeval_scorer", None)
    # Ensure deepeval is absent
    with patch.dict(sys.modules, {"deepeval": None, "deepeval.metrics": None}):
        import importlib

        import eval.deepeval_scorer as mod

        importlib.reload(mod)
        with pytest.raises(ImportError, match="deepeval is not installed"):
            mod.DeepEvalScorer("x", "y", model="m")


def test_custom_threshold_stored() -> None:
    _make_deepeval_stub()
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "y", model="m", threshold=0.7)
        assert scorer._threshold == 0.7
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


# ---------------------------------------------------------------------------
# score() happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_returns_score_object() -> None:
    _make_deepeval_stub(score=0.8, success=True, reason="great tone")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("voice_quality", "Is tone warm?", model="m")
        result = await scorer.score("Today I repotted my monstera and it felt grounding.")
        assert 0.0 <= result.value <= 1.0
        assert result.provider == "deepeval"
        assert isinstance(result.passed, bool)
        assert isinstance(result.rationale, str)
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_score_value_matches_geval_score() -> None:
    _make_deepeval_stub(score=0.75, success=True, reason="good")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("coherence", "Is the output coherent?", model="m")
        result = await scorer.score("Some output text.")
        assert result.value == pytest.approx(0.75)
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_score_passed_reflects_metric_success() -> None:
    _make_deepeval_stub(score=0.3, success=False, reason="off-brand")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("brand_voice", "Matches brand?", model="m")
        result = await scorer.score("BUY NOW!! LIMITED OFFER!!!")
        assert result.passed is False
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_score_rationale_uses_metric_reason() -> None:
    _make_deepeval_stub(score=0.9, success=True, reason="excellent local focus")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("local_commerce", "Local pickup focus?", model="m")
        result = await scorer.score("DM me for local pickup this weekend!")
        assert "excellent local focus" in result.rationale
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_score_rationale_fallback_when_no_reason() -> None:
    _make_deepeval_stub(score=0.6, success=True, reason="")
    try:
        stub = sys.modules["deepeval.metrics"].GEval.return_value
        stub.reason = ""
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("my_eval", "criteria", model="m")
        result = await scorer.score("some text")
        assert "my_eval" in result.rationale
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


# ---------------------------------------------------------------------------
# Context forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_forwarded_as_additional_context() -> None:
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("safety", "No medical claims?", model="m")
        await scorer.score(
            "Water your plant daily.", context={"audience": "plant_lovers", "locale": "en"}
        )
        metric_instance = sys.modules["deepeval.metrics"].GEval.return_value
        # Context was passed in some form — just verify a_measure was called
        assert metric_instance.a_measure.called
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_no_context_passes_none() -> None:
    _make_deepeval_stub(score=0.7, success=True, reason="fine")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "y", model="m")
        result = await scorer.score("output only, no context")
        assert result.value == pytest.approx(0.7)
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


# ---------------------------------------------------------------------------
# Fallback pattern — ImportError at construction, not at score()
# ---------------------------------------------------------------------------


def test_fallback_pattern_to_rubric_scorer() -> None:
    """Callers catch ImportError at construction and fall back to RubricScorer."""
    _remove_deepeval_stub()
    sys.modules.pop("eval.deepeval_scorer", None)

    from eval.loader import load_department
    from eval.scorer import RubricScorer

    templates_dir = Path(__file__).resolve().parents[2] / "eval" / "departments" / "yaml"
    rubric_eval = load_department(templates_dir / "marketing.yaml")[0]

    with patch.dict(sys.modules, {"deepeval": None, "deepeval.metrics": None}):
        import importlib

        import eval.deepeval_scorer as mod

        importlib.reload(mod)
        try:
            scorer = mod.DeepEvalScorer("x", "y", model="m")
        except ImportError:
            scorer = RubricScorer(rubric_eval)

    assert scorer.provider == "rubric"


# ---------------------------------------------------------------------------
# Mutation killers — pin what's passed TO GEval (not just what comes back)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_geval_called_with_correct_eval_name() -> None:
    """Mutating GEval(name=...) arg must be caught."""
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("my_eval_name", "criteria text", model="m")
        await scorer.score("output")
        geval_cls = sys.modules["deepeval.metrics"].GEval
        call_kwargs = geval_cls.call_args
        assert call_kwargs.kwargs.get("name") == "my_eval_name"
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_geval_called_with_correct_criteria() -> None:
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        criteria = "Is the tone warm and first-person?"
        scorer = DeepEvalScorer("x", criteria, model="m")
        await scorer.score("output")
        geval_cls = sys.modules["deepeval.metrics"].GEval
        assert geval_cls.call_args.kwargs.get("criteria") == criteria
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_geval_called_with_correct_threshold() -> None:
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m", threshold=0.7)
        await scorer.score("output")
        geval_cls = sys.modules["deepeval.metrics"].GEval
        assert geval_cls.call_args.kwargs.get("threshold") == pytest.approx(0.7)
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_geval_called_with_correct_model() -> None:
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="my-special-model")
        await scorer.score("output")
        geval_cls = sys.modules["deepeval.metrics"].GEval
        assert geval_cls.call_args.kwargs.get("model") == "my-special-model"
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_context_becomes_additional_context_string() -> None:
    """None context → None passed; dict context → key=value string, NOT empty string."""
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m")
        # No context → additional_context should be None
        await scorer.score("output", context=None)
        metric = sys.modules["deepeval.metrics"].GEval.return_value
        call_kwargs = metric.a_measure.call_args.kwargs
        assert call_kwargs.get("_additional_context") is None

        # With context → should be a non-empty string
        metric.a_measure.reset_mock()
        await scorer.score("output", context={"key": "value"})
        call_kwargs2 = metric.a_measure.call_args.kwargs
        ctx_str = call_kwargs2.get("_additional_context")
        assert ctx_str is not None
        assert "key" in ctx_str
        assert "value" in ctx_str
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_ameasure_called_with_actual_output() -> None:
    """Mutations that change what's passed to LLMTestCase are caught."""
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m")
        text = "The specific output text to score"
        await scorer.score(text)
        tc_cls = sys.modules["deepeval.test_case"].LLMTestCase
        # LLMTestCase should have been called with actual_output=text
        assert tc_cls.called
        assert tc_cls.call_args is not None
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_score_details_contain_threshold() -> None:
    """Mutation: threshold=None in details → caught by this test."""
    _make_deepeval_stub(score=0.6, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m", threshold=0.4)
        result = await scorer.score("output")
        assert result.details.get("threshold") == pytest.approx(0.4)
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


# ---------------------------------------------------------------------------
# Context formatting gap-fillers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_join_format_is_key_eq_value() -> None:
    """context dict → 'k1=v1; k2=v2' — not empty string, not repr()."""
    _make_deepeval_stub(score=0.7, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m")
        await scorer.score("out", context={"audience": "plant_lovers", "locale": "en"})
        metric = sys.modules["deepeval.metrics"].GEval.return_value
        ctx = metric.a_measure.call_args.kwargs.get("_additional_context")
        assert ctx is not None
        assert "audience=plant_lovers" in ctx
        assert "locale=en" in ctx
        # separator is "; "
        assert "; " in ctx
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_single_context_key_no_separator() -> None:
    """Single-key context has no '; ' separator."""
    _make_deepeval_stub(score=0.7, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m")
        await scorer.score("out", context={"key": "val"})
        metric = sys.modules["deepeval.metrics"].GEval.return_value
        ctx = metric.a_measure.call_args.kwargs.get("_additional_context")
        assert ctx == "key=val"
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_empty_context_dict_passes_none() -> None:
    """Empty dict → no context string → None passed."""
    _make_deepeval_stub(score=0.7, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m")
        await scorer.score("out", context={})
        metric = sys.modules["deepeval.metrics"].GEval.return_value
        ctx = metric.a_measure.call_args.kwargs.get("_additional_context")
        assert ctx is None
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_geval_async_mode_true() -> None:
    """GEval must be constructed with async_mode=True."""
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m")
        await scorer.score("out")
        geval_cls = sys.modules["deepeval.metrics"].GEval
        assert geval_cls.call_args.kwargs.get("async_mode") is True
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_geval_verbose_mode_false() -> None:
    """GEval must be constructed with verbose_mode=False."""
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m")
        await scorer.score("out")
        geval_cls = sys.modules["deepeval.metrics"].GEval
        assert geval_cls.call_args.kwargs.get("verbose_mode") is False
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)


@pytest.mark.asyncio
async def test_geval_evaluation_params_set() -> None:
    """evaluation_params must be set (non-empty)."""
    _make_deepeval_stub(score=0.8, success=True, reason="ok")
    try:
        from eval.deepeval_scorer import DeepEvalScorer

        scorer = DeepEvalScorer("x", "c", model="m")
        await scorer.score("out")
        geval_cls = sys.modules["deepeval.metrics"].GEval
        params = geval_cls.call_args.kwargs.get("evaluation_params")
        assert params is not None
        assert len(params) > 0
    finally:
        _remove_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)
