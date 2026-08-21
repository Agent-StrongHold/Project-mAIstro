"""Chaos / fault-injection tests for DeepEvalScorer (ADR-060).

Tests how DeepEvalScorer behaves under hostile conditions:
  - GEval raises mid-score
  - metric.score is None / NaN / negative / >1
  - metric.success / metric.reason are None
  - Malformed context
  - Extreme outputs (empty, huge, unicode, binary-ish)
"""

from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _make_stub(score=0.8, success=True, reason="ok", side_effect=None):
    stub = types.ModuleType("deepeval")
    metrics_mod = types.ModuleType("deepeval.metrics")
    mock_metric = MagicMock()
    mock_metric.score = score
    mock_metric.success = success
    mock_metric.reason = reason
    if side_effect is not None:
        mock_metric.a_measure = AsyncMock(side_effect=side_effect)
    else:
        mock_metric.a_measure = AsyncMock(return_value=score)
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
    return mock_metric


def _teardown():
    for key in list(sys.modules):
        if key == "deepeval" or key.startswith("deepeval."):
            del sys.modules[key]
    sys.modules.pop("eval.deepeval_scorer", None)


@pytest.fixture(autouse=True)
def cleanup():
    yield
    _teardown()


# ---------------------------------------------------------------------------
# Fault injection: a_measure raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_geval_raises_runtime_error_propagates() -> None:
    """GEval raising mid-score propagates — callers must handle it."""
    _make_stub(side_effect=RuntimeError("LLM timeout"))
    from eval.deepeval_scorer import DeepEvalScorer

    scorer = DeepEvalScorer("x", "criteria", model="m")
    with pytest.raises(RuntimeError, match="LLM timeout"):
        await scorer.score("some output")


@pytest.mark.asyncio
async def test_geval_raises_value_error_propagates() -> None:
    _make_stub(side_effect=ValueError("bad response"))
    from eval.deepeval_scorer import DeepEvalScorer

    scorer = DeepEvalScorer("x", "criteria", model="m")
    with pytest.raises(ValueError, match="bad response"):
        await scorer.score("output")


# ---------------------------------------------------------------------------
# Fault injection: metric.score edge values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_none_clamps_to_zero() -> None:
    """metric.score = None → value = 0.0 (float(None or 0.0))."""
    _make_stub(score=None, success=False, reason="no score")
    from eval.deepeval_scorer import DeepEvalScorer

    scorer = DeepEvalScorer("x", "criteria", model="m")
    result = await scorer.score("output")
    assert result.value == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_score_zero_value() -> None:
    _make_stub(score=0.0, success=False, reason="fail")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("out")
    assert result.value == pytest.approx(0.0)
    assert result.passed is False


@pytest.mark.asyncio
async def test_score_one_value() -> None:
    _make_stub(score=1.0, success=True, reason="perfect")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("out")
    assert result.value == pytest.approx(1.0)
    assert result.passed is True


@pytest.mark.asyncio
async def test_score_nan_stored_as_nan() -> None:
    """NaN from GEval flows through — contract layer should detect it."""
    _make_stub(score=float("nan"), success=False, reason="nan")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("out")
    assert math.isnan(result.value)


# ---------------------------------------------------------------------------
# Fault injection: metric.success / reason are None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_none_coerces_to_false() -> None:
    mock = _make_stub(score=0.4, success=None, reason="ok")
    mock.success = None
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("out")
    assert result.passed is False  # bool(None) == False


@pytest.mark.asyncio
async def test_reason_none_uses_fallback_rationale() -> None:
    mock = _make_stub(score=0.6, success=True, reason=None)
    mock.reason = None
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("my_eval", "c", model="m").score("out")
    assert "my_eval" in result.rationale


@pytest.mark.asyncio
async def test_reason_empty_string_uses_fallback_rationale() -> None:
    _make_stub(score=0.6, success=True, reason="")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("my_eval", "c", model="m").score("out")
    assert "my_eval" in result.rationale


# ---------------------------------------------------------------------------
# Extreme inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_output() -> None:
    _make_stub(score=0.1, success=False, reason="empty")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("")
    assert 0.0 <= result.value <= 1.0


@pytest.mark.asyncio
async def test_whitespace_only_output() -> None:
    _make_stub(score=0.1, success=False, reason="whitespace")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("   \n\t  ")
    assert result is not None


@pytest.mark.asyncio
async def test_very_long_output() -> None:
    """10k-char output should not crash the scorer."""
    _make_stub(score=0.5, success=True, reason="long")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("word " * 2000)
    assert 0.0 <= result.value <= 1.0


@pytest.mark.asyncio
async def test_unicode_output() -> None:
    _make_stub(score=0.7, success=True, reason="unicode ok")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("日本語 العربية русский 🌿")
    assert 0.0 <= result.value <= 1.0


@pytest.mark.asyncio
async def test_control_characters_in_output() -> None:
    _make_stub(score=0.3, success=False, reason="control")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("\x00\x01\x02\x03")
    assert result is not None


# ---------------------------------------------------------------------------
# Malformed context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_with_none_values() -> None:
    _make_stub(score=0.5, success=True, reason="ok")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("out", context={"key": None})
    assert result is not None


@pytest.mark.asyncio
async def test_context_with_unicode_keys() -> None:
    _make_stub(score=0.5, success=True, reason="ok")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("out", context={"日本語": "value"})
    assert 0.0 <= result.value <= 1.0


@pytest.mark.asyncio
async def test_context_with_nested_values_serialises() -> None:
    """Context values are stringified via f-string — nested dicts become repr."""
    _make_stub(score=0.5, success=True, reason="ok")
    from eval.deepeval_scorer import DeepEvalScorer

    result = await DeepEvalScorer("x", "c", model="m").score("out", context={"nested": {"a": 1}})
    assert result is not None
