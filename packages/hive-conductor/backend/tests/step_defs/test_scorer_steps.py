"""pytest-bdd step definitions for features/scorer.feature."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

FEATURES = Path(__file__).resolve().parents[3] / "features"
scenarios(str(FEATURES / "scorer.feature"))

_TEMPLATES = Path(__file__).resolve().parents[3] / "eval" / "departments" / "yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deepeval_stub(score: float = 0.8, success: bool = True, reason: str = "ok") -> None:
    stub = types.ModuleType("deepeval")
    metrics_mod = types.ModuleType("deepeval.metrics")
    mock_metric = MagicMock()
    mock_metric.score = score
    mock_metric.success = success
    mock_metric.reason = reason
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


def _remove_deepeval_stub() -> None:
    for key in list(sys.modules):
        if key == "deepeval" or key.startswith("deepeval."):
            del sys.modules[key]
    sys.modules.pop("eval.deepeval_scorer", None)


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the hive-conductor eval system is loaded")
def eval_system_loaded() -> None:
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse('a department YAML template "{name}" exists'))
def dept_template_exists(name: str) -> None:
    assert (_TEMPLATES / name).exists(), f"Missing template: {name}"


@given("deepeval is not installed in this environment")
def deepeval_not_installed(monkeypatch) -> None:
    _remove_deepeval_stub()
    monkeypatch.setitem(sys.modules, "deepeval", None)
    monkeypatch.setitem(sys.modules, "deepeval.metrics", None)


@given("deepeval is installed")
def deepeval_installed() -> None:
    _make_deepeval_stub()


@given(parsers.parse("a {provider} scorer"), target_fixture="scorer")
def make_scorer(provider: str) -> object:
    from eval.loader import load_department
    from eval.scorer import RubricScorer

    rubric = load_department(_TEMPLATES / "marketing.yaml")[0]
    if provider == "rubric":
        return RubricScorer(rubric)
    if provider == "deepeval":
        _make_deepeval_stub()
        sys.modules.pop("eval.deepeval_scorer", None)
        from eval.deepeval_scorer import DeepEvalScorer

        return DeepEvalScorer("voice_quality", "Is tone warm?", model="fake")
    raise ValueError(f"Unknown provider: {provider}")


@given("a rubric scorer", target_fixture="scorer")
def rubric_scorer() -> object:
    from eval.loader import load_department
    from eval.scorer import RubricScorer

    rubric = load_department(_TEMPLATES / "marketing.yaml")[0]
    return RubricScorer(rubric)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I wrap its first eval dimension in a RubricScorer", target_fixture="scorer")
def wrap_rubric_scorer() -> object:
    from eval.loader import load_department
    from eval.scorer import RubricScorer

    return RubricScorer(load_department(_TEMPLATES / "marketing.yaml")[0])


@when("I attempt to construct a DeepEvalScorer", target_fixture="construction_error")
def attempt_deepeval_construction() -> Exception | None:
    sys.modules.pop("eval.deepeval_scorer", None)
    import importlib

    import eval.deepeval_scorer as mod

    importlib.reload(mod)
    try:
        mod.DeepEvalScorer("x", "y", model="m")
        return None
    except ImportError as exc:
        return exc


@when("I construct a scorer with DeepEval-or-fallback logic", target_fixture="scorer")
def construct_with_fallback(monkeypatch) -> object:
    from eval.loader import load_department
    from eval.scorer import RubricScorer

    rubric = load_department(_TEMPLATES / "marketing.yaml")[0]
    sys.modules.pop("eval.deepeval_scorer", None)
    import importlib

    import eval.deepeval_scorer as mod

    importlib.reload(mod)
    try:
        return mod.DeepEvalScorer("x", "y", model="m")
    except ImportError:
        return RubricScorer(rubric)


@when(
    parsers.parse('I construct a DeepEvalScorer with criteria "{criteria}"'),
    target_fixture="scorer",
)
def construct_deepeval_scorer(criteria: str) -> object:
    sys.modules.pop("eval.deepeval_scorer", None)
    from eval.deepeval_scorer import DeepEvalScorer

    return DeepEvalScorer("test_eval", criteria, model="fake")


@when(parsers.parse('I score "{output}"'), target_fixture="score_result")
def score_output(output: str, scorer) -> object:
    import asyncio

    return asyncio.run(scorer.score(output))


@when("I score any text", target_fixture="score_result")
def score_any_text(scorer) -> object:
    import asyncio

    return asyncio.run(scorer.score("sample marketing copy for testing purposes"))


@when("I score an empty string", target_fixture="score_result")
def score_empty(scorer) -> object:
    import asyncio

    return asyncio.run(scorer.score(""))


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse('the scorer provider is "{expected}"'))
def check_provider(scorer, expected: str) -> None:
    assert scorer.provider == expected


@then("scoring any text returns a Score with value between 0.0 and 1.0")
def check_score_range(scorer) -> None:
    import asyncio

    result = asyncio.run(scorer.score("sample text"))
    assert 0.0 <= result.value <= 1.0


@then(parsers.parse('an ImportError is raised with "{msg}"'))
def check_import_error(construction_error, msg: str) -> None:
    assert isinstance(construction_error, ImportError)
    assert msg in str(construction_error)


@then("the system starts without error")
def no_startup_error(scorer) -> None:
    assert scorer is not None


@then("the score value is between 0.0 and 1.0 inclusive")
def score_in_range(score_result) -> None:
    assert 0.0 <= score_result.value <= 1.0


@then("the score passed field is a boolean")
def score_passed_is_bool(score_result) -> None:
    assert isinstance(score_result.passed, bool)


@then(parsers.parse('the score provider is "{expected}"'))
def check_score_provider(score_result, expected: str) -> None:
    assert score_result.provider == expected


@then("no exception is raised")
def no_exception(score_result) -> None:
    assert score_result is not None


@then("the default threshold is 0.5")
def check_default_threshold(scorer) -> None:
    assert scorer._threshold == pytest.approx(0.5)
