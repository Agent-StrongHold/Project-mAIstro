"""Tests for the second-opinion LLM regression judge (stub llm_call — no
network). The fail-closed contract (#307): every judge failure is an
*unavailable* verdict — status "unavailable", score None, a named cause —
never a passing number."""

from __future__ import annotations

from typing import Any

from maistro_rsi.regression_judge import judge_regression_verdict


def _stub(content: str):
    def call(messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        return {"content": content}

    return call


def _raising(exc: BaseException):
    def call(messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        raise exc

    return call


def test_empty_diff_scores_perfect_without_calling_llm() -> None:
    def call(*a, **k):
        raise AssertionError("must not call the LLM for an empty diff")

    verdict = judge_regression_verdict("", "target.py", call)
    assert verdict.status == "pass"
    assert verdict.score == 1.0
    assert "empty diff" in verdict.rationale
    assert verdict.cause is None


def test_parses_valid_json_verdict_below_threshold_is_reject() -> None:
    verdict = judge_regression_verdict(
        "diff --git a/x.py b/x.py\n+x = 1\n",
        "x.py",
        _stub('{"score": 0.2, "rationale": "narrows list to str() on line 5"}'),
    )
    assert verdict.status == "reject"
    assert verdict.score == 0.2
    assert "narrows list to str()" in verdict.rationale
    assert verdict.cause is None


def test_valid_json_verdict_above_threshold_is_pass() -> None:
    verdict = judge_regression_verdict(
        "diff", "x.py", _stub('{"score": 0.9, "rationale": "no concerns"}')
    )
    assert verdict.status == "pass"
    assert verdict.score == 0.9


def test_clamps_out_of_range_score() -> None:
    verdict = judge_regression_verdict("diff", "x.py", _stub('{"score": 5.0, "rationale": "w"}'))
    assert verdict.score == 1.0
    assert verdict.status == "pass"


def test_json_embedded_in_prose_is_extracted() -> None:
    reply = 'Here is my review:\n{"score": 0.9, "rationale": "looks fine"}\nThanks.'
    verdict = judge_regression_verdict("diff", "x.py", _stub(reply))
    assert verdict.status == "pass"
    assert verdict.score == 0.9
    assert verdict.rationale == "looks fine"


def test_gateway_raise_is_unavailable_with_cause_and_no_score() -> None:
    verdict = judge_regression_verdict("diff", "x.py", _raising(RuntimeError("gateway 500")))
    assert verdict.status == "unavailable"
    assert verdict.score is None
    assert verdict.cause == "gateway_error"


def test_timeout_raise_is_unavailable_with_timeout_cause() -> None:
    verdict = judge_regression_verdict("diff", "x.py", _raising(TimeoutError("slow gateway")))
    assert verdict.status == "unavailable"
    assert verdict.score is None
    assert verdict.cause == "timeout"


def test_malformed_json_reply_is_unavailable_unparsable() -> None:
    verdict = judge_regression_verdict("diff", "x.py", _stub("not json at all"))
    assert verdict.status == "unavailable"
    assert verdict.score is None
    assert verdict.cause == "unparsable_reply"


def test_reply_missing_score_key_is_unavailable_unparsable() -> None:
    verdict = judge_regression_verdict(
        "diff", "x.py", _stub('{"rationale": "forgot the score field"}')
    )
    assert verdict.status == "unavailable"
    assert verdict.score is None
    assert verdict.cause == "unparsable_reply"


def test_non_numeric_score_is_unavailable_unparsable() -> None:
    verdict = judge_regression_verdict(
        "diff", "x.py", _stub('{"score": "high", "rationale": "words not numbers"}')
    )
    assert verdict.status == "unavailable"
    assert verdict.score is None
    assert verdict.cause == "unparsable_reply"


def test_non_dict_json_reply_is_unavailable_unparsable() -> None:
    # Valid JSON, but not an object — data.get("score") would be meaningless.
    verdict = judge_regression_verdict("diff", "x.py", _stub("[1, 2, 3]"))
    assert verdict.status == "unavailable"
    assert verdict.score is None
    assert verdict.cause == "unparsable_reply"


def test_oversized_diff_is_unavailable_without_calling_llm() -> None:
    # 3x the 8000-char slice cap: the judge would see under half the diff —
    # refuse to rule on a partial view instead of judging it (#307).
    def call(*a, **k):
        raise AssertionError("must not call the LLM for an oversized diff")

    verdict = judge_regression_verdict("x" * 24000, "x.py", call)
    assert verdict.status == "unavailable"
    assert verdict.score is None
    assert verdict.cause == "oversized_diff"
    assert "24000" in verdict.rationale


def test_moderately_truncated_diff_is_still_judged() -> None:
    # 12000 chars slices to 8000 (≈67% retained, above the 50% floor): the
    # judge still rules on the (bounded) partial view, as before #307.
    verdict = judge_regression_verdict(
        "x" * 12000, "x.py", _stub('{"score": 0.9, "rationale": "fine"}')
    )
    assert verdict.status == "pass"
    assert verdict.score == 0.9
