"""Tests for the second-opinion LLM regression judge (stub llm_call — no network)."""

from __future__ import annotations

from typing import Any

from maistro_rsi.regression_judge import judge_regression


def _stub(content: str):
    def call(messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        return {"content": content}

    return call


def test_empty_diff_scores_perfect_without_calling_llm() -> None:
    def call(*a, **k):
        raise AssertionError("must not call the LLM for an empty diff")

    score, rationale = judge_regression("", "target.py", call)
    assert score == 1.0 and "empty diff" in rationale


def test_parses_valid_json_verdict() -> None:
    score, rationale = judge_regression(
        "diff --git a/x.py b/x.py\n+x = 1\n",
        "x.py",
        _stub('{"score": 0.2, "rationale": "narrows list to str() on line 5"}'),
    )
    assert score == 0.2
    assert "narrows list to str()" in rationale


def test_clamps_out_of_range_score() -> None:
    score, _ = judge_regression("diff", "x.py", _stub('{"score": 5.0, "rationale": "whatever"}'))
    assert score == 1.0


def test_unparsable_reply_falls_back_to_neutral() -> None:
    score, rationale = judge_regression("diff", "x.py", _stub("not json at all"))
    assert score == 0.7
    assert "unparsable" in rationale


def test_llm_call_exception_falls_back_to_neutral() -> None:
    def raising(*a, **k):
        raise RuntimeError("gateway 500")

    score, rationale = judge_regression("diff", "x.py", raising)
    assert score == 0.7
    assert "unavailable" in rationale


def test_json_embedded_in_prose_is_extracted() -> None:
    reply = 'Here is my review:\n{"score": 0.9, "rationale": "looks fine"}\nThanks.'
    score, rationale = judge_regression("diff", "x.py", _stub(reply))
    assert score == 0.9
    assert rationale == "looks fine"


def test_custom_fallback_score_honored_on_error() -> None:
    def raising(*a, **k):
        raise RuntimeError("boom")

    score, _ = judge_regression("diff", "x.py", raising, fallback_score=0.5)
    assert score == 0.5
