"""I8: Constant-Time Secret Comparison — Hypothesis property-based tests."""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security.secret_equal import secret_equal


class SecretEqualMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.expected = "secret-token-123"
        self.results: list[bool] = []

    @rule(
        candidate=st.text(min_size=0, max_size=100),
    )
    def compare_text(self, candidate):
        result = secret_equal(candidate, self.expected)
        self.results.append(result)

    @rule(
        candidate=st.one_of(st.integers(), st.floats(), st.none(), st.booleans(), st.lists(st.integers())),
    )
    def compare_non_string(self, candidate):
        result = secret_equal(candidate, self.expected)
        self.results.append(result)
        assert result is False

    @invariant()
    def results_are_bool(self):
        for r in self.results:
            assert isinstance(r, bool)


TestSecretEqualMachine = SecretEqualMachine.TestCase


@given(a=st.text(min_size=0, max_size=200))
@settings(max_examples=200)
def test_equal_strings_return_true(a):
    assert secret_equal(a, a) is True


@given(
    a=st.text(min_size=0, max_size=100),
    b=st.text(min_size=0, max_size=100),
)
@settings(max_examples=200)
def test_different_strings_return_false(a, b):
    assume(a != b)
    assert secret_equal(a, b) is False


@given(
    value=st.one_of(
        st.integers(),
        st.floats(),
        st.none(),
        st.booleans(),
        st.lists(st.integers()),
        st.tuples(st.integers()),
        st.dictionaries(st.text(), st.text()),
    )
)
@settings(max_examples=100)
def test_non_string_returns_false(value):
    assert secret_equal(value, "any-string") is False


@given(value=st.one_of(st.integers(), st.floats(), st.none()))
@settings(max_examples=50)
def test_both_non_string_returns_false(value):
    assert secret_equal(value, value) is False


def test_case_sensitive():
    assert secret_equal("ABC", "abc") is False
    assert secret_equal("abc", "abc") is True


@given(c=st.characters(whitelist_categories=("L", "N")))
@settings(max_examples=50)
def test_case_sensitive_per_character(c):
    lower = c.lower()
    upper = c.upper()
    if lower != upper:
        assert secret_equal(lower, upper) is False


@given(a=st.text(min_size=1, max_size=50))
@settings(max_examples=50)
def test_empty_vs_nonempty(a):
    assert secret_equal("", a) is False
    assert secret_equal(a, "") is False


def test_both_empty():
    assert secret_equal("", "") is True


@given(
    prefix=st.text(min_size=1, max_size=20),
    suffix=st.text(min_size=1, max_size=20),
)
@settings(max_examples=50)
def test_prefix_suffix_distinguish(prefix, suffix):
    assume(prefix != suffix)
    assert secret_equal(prefix + suffix, prefix) is False
    assert secret_equal(prefix + suffix, suffix) is False


@given(s=st.text(min_size=1, max_size=50))
@settings(max_examples=50)
def test_trailing_whitespace_matters(s):
    assert secret_equal(s, s + " ") is False
    assert secret_equal(s + " ", s) is False


@given(
    s=st.text(min_size=1, max_size=50),
)
@settings(max_examples=50)
def test_unicode_normalization(s):
    result = secret_equal(s, s)
    assert result is True


@given(
    a=st.text(min_size=0, max_size=100),
    b=st.text(min_size=0, max_size=100),
)
@settings(max_examples=100)
def test_commutative(a, b):
    assert secret_equal(a, b) == secret_equal(b, a)
