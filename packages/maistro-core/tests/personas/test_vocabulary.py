"""Vocabulary op tests (ADR-060 §1)."""

from __future__ import annotations

import pytest

from maistro.personas.vocabulary import evaluate


def test_keywords_any() -> None:
    assert evaluate({"op": "keywords_any", "words": ["water", "soil"]}, "Add Water daily", {})
    assert not evaluate({"op": "keywords_any", "words": ["cure"]}, "just a plant", {})


def test_keywords_none() -> None:
    assert evaluate({"op": "keywords_none", "words": ["cure"]}, "a calm ritual", {})
    assert not evaluate({"op": "keywords_none", "words": ["cure"]}, "this CURES anxiety", {})


def test_regex_and_absent() -> None:
    assert evaluate({"op": "regex", "pattern": r"\$\d+"}, "only $15 today", {})
    assert evaluate({"op": "regex_absent", "pattern": r"\$\d+"}, "DM for price", {})


def test_regex_flags() -> None:
    assert evaluate({"op": "regex", "pattern": "hello", "flags": "i"}, "HELLO there", {})


def test_regex_count_bounds() -> None:
    assert evaluate({"op": "regex_count", "pattern": "!", "max": 2}, "wow! nice!", {})
    assert not evaluate({"op": "regex_count", "pattern": "!", "max": 1}, "wow! nice!", {})
    assert evaluate({"op": "regex_count", "pattern": r"#\w+", "min": 1}, "#plants rock", {})


def test_word_count() -> None:
    assert evaluate({"op": "word_count", "min": 2, "max": 3}, "two small words", {})
    assert not evaluate({"op": "word_count", "max": 2}, "three small words", {})


def test_metric_long_word_ratio() -> None:
    check = {"op": "metric", "name": "long_word_ratio", "cmp": "lt", "value": 0.08}
    assert evaluate(check, "a calm short post about plants", {})
    assert not evaluate(check, "extraordinarily complicated pharmacological terminology", {})


def test_metric_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown metric"):
        evaluate({"op": "metric", "name": "nope", "cmp": "lt", "value": 1}, "x", {})


def test_any_all_composition() -> None:
    sub_hit = {"op": "keywords_any", "words": ["water"]}
    sub_miss = {"op": "keywords_any", "words": ["zzz"]}
    assert evaluate({"op": "any", "of": [sub_miss, sub_hit]}, "water it", {})
    assert not evaluate({"op": "all", "of": [sub_miss, sub_hit]}, "water it", {})


def test_registered_predicate() -> None:
    check = {
        "op": "registered",
        "name": "keyword_count_max",
        "args": {"words": ["buy now", "subscribe"], "max": 1},
    }
    assert evaluate(check, "please subscribe", {})
    assert not evaluate(check, "buy now and subscribe", {})


def test_registered_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown registered predicate"):
        evaluate({"op": "registered", "name": "nope"}, "x", {})


def test_unknown_op_raises() -> None:
    with pytest.raises(ValueError, match="Unknown check op"):
        evaluate({"op": "bogus"}, "x", {})


def test_slice_restriction() -> None:
    check = {"op": "keywords_any", "words": ["hook"], "slice_end": 4}
    assert evaluate(check, "hook comes first", {})
    assert not evaluate(check, "later comes the hook", {})
