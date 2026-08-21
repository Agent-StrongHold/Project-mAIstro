"""Property-based tests for the check vocabulary (ADR-060).

Uses Hypothesis to verify invariants that must hold for ALL inputs,
not just the examples in unit tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.vocabulary import evaluate

pytestmark = [pytest.mark.scope]

# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

printable_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=500,
)

word_list = st.lists(
    st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=20),
    min_size=1,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Invariant: evaluate() always returns bool
# ---------------------------------------------------------------------------


@given(text=printable_text)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_evaluate_always_returns_bool_keywords_any(text: str) -> None:
    spec = {"op": "keywords_any", "words": ["calm", "grounding"]}
    result = evaluate(spec, text, {})
    assert isinstance(result, bool)


@given(text=printable_text)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_evaluate_always_returns_bool_keywords_none(text: str) -> None:
    spec = {"op": "keywords_none", "words": ["cure", "diagnose"]}
    result = evaluate(spec, text, {})
    assert isinstance(result, bool)


@given(text=printable_text)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_evaluate_always_returns_bool_word_count(text: str) -> None:
    spec = {"op": "word_count", "max": 50}
    result = evaluate(spec, text, {})
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# keywords_any properties
# ---------------------------------------------------------------------------


@given(text=printable_text)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_keywords_any_empty_words_always_false(text: str) -> None:
    """Empty word list can never match anything."""
    spec = {"op": "keywords_any", "words": []}
    assert evaluate(spec, text, {}) is False


@given(words=word_list)
@settings(max_examples=100)
def test_keywords_any_word_present_returns_true(words: list[str]) -> None:
    """If any word from the list is in the text, result must be True."""
    assume(all(len(w) > 0 for w in words))
    target = words[0].lower()
    spec = {"op": "keywords_any", "words": words}
    result = evaluate(spec, target + " extra words", {})
    assert result is True


@given(words=word_list, text=printable_text)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_keywords_any_complement_of_none(words: list[str], text: str) -> None:
    """keywords_any and keywords_none on the same words are complementary."""
    any_spec = {"op": "keywords_any", "words": words}
    none_spec = {"op": "keywords_none", "words": words}
    any_result = evaluate(any_spec, text, {})
    none_result = evaluate(none_spec, text, {})
    assert any_result != none_result or (not any_result and none_result)


# ---------------------------------------------------------------------------
# word_count properties
# ---------------------------------------------------------------------------


@given(n=st.integers(min_value=1, max_value=200))
@settings(max_examples=100)
def test_word_count_max_boundary(n: int) -> None:
    """Exactly n words passes a max=n constraint."""
    text = " ".join(["word"] * n)
    spec = {"op": "word_count", "max": n}
    assert evaluate(spec, text, {}) is True


@given(n=st.integers(min_value=1, max_value=200))
@settings(max_examples=100)
def test_word_count_exceeds_max_fails(n: int) -> None:
    """n+1 words fails a max=n constraint."""
    text = " ".join(["word"] * (n + 1))
    spec = {"op": "word_count", "max": n}
    assert evaluate(spec, text, {}) is False


@given(n=st.integers(min_value=1, max_value=200))
@settings(max_examples=100)
def test_word_count_min_boundary(n: int) -> None:
    """Exactly n words passes a min=n constraint."""
    text = " ".join(["word"] * n)
    spec = {"op": "word_count", "min": n}
    assert evaluate(spec, text, {}) is True


# ---------------------------------------------------------------------------
# regex properties
# ---------------------------------------------------------------------------


@given(text=printable_text)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_regex_always_returns_bool(text: str) -> None:
    spec = {"op": "regex", "pattern": r"\$\d+"}
    result = evaluate(spec, text, {})
    assert isinstance(result, bool)


@given(text=printable_text)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_regex_absent_always_returns_bool(text: str) -> None:
    spec = {"op": "regex_absent", "pattern": r"\bcure\b", "flags": "i"}
    result = evaluate(spec, text, {})
    assert isinstance(result, bool)


@given(text=printable_text)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_regex_and_absent_are_complement(text: str) -> None:
    """regex and regex_absent on same pattern are strict complements."""
    pattern = r"\btest\b"
    match = evaluate({"op": "regex", "pattern": pattern}, text, {})
    absent = evaluate({"op": "regex_absent", "pattern": pattern}, text, {})
    assert match != absent, f"regex and regex_absent both returned {match} for {text!r}"


# ---------------------------------------------------------------------------
# Combinator (any/all) properties
# ---------------------------------------------------------------------------


@given(text=printable_text)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_all_with_always_true_sub_ops(text: str) -> None:
    """all over vacuously-true ops (empty keywords_none) stays True."""
    spec = {
        "op": "all",
        "of": [
            {"op": "keywords_none", "words": ["xyzzy_never_appears_1a2b3c"]},
            {"op": "keywords_none", "words": ["xyzzy_never_appears_4d5e6f"]},
        ],
    }
    assert evaluate(spec, text, {}) is True


@given(text=printable_text)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_any_with_always_false_sub_ops(text: str) -> None:
    """any over always-False ops (empty keywords_any) stays False."""
    spec = {
        "op": "any",
        "of": [
            {"op": "keywords_any", "words": []},
            {"op": "keywords_any", "words": []},
        ],
    }
    assert evaluate(spec, text, {}) is False
