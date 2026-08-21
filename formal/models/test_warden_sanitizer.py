"""I20: Warden Sanitizer — Input Sanitization — Hypothesis property-based tests."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security.warden.sanitizer import sanitize


class SanitizerMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.sanitized_count = 0

    @rule(
        text=st.text(min_size=0, max_size=500),
    )
    def sanitize_text(self, text):
        result = sanitize(text)
        assert isinstance(result, str)
        self.sanitized_count += 1

    @invariant()
    def no_zero_width_chars(self):
        pass

    @invariant()
    def sanitized_count_non_negative(self):
        assert self.sanitized_count >= 0


TestSanitizerMachine = SanitizerMachine.TestCase


def test_zero_width_chars_stripped():
    text = "hello\u200bworld\u200c\u200d"
    result = sanitize(text)
    assert result == "helloworld"


def test_zero_width_chars_all_removed():
    text = "\u200b\u200c\u200d\u200e\u200f\ufeff"
    result = sanitize(text)
    assert all(c not in result for c in "\u200b\u200c\u200d\u200e\u200f\ufeff")


def test_multiple_spaces_collapsed():
    text = "hello    world   foo"
    result = sanitize(text)
    assert result == "hello world foo"


def test_leading_trailing_stripped():
    text = "   hello world   "
    result = sanitize(text)
    assert result == "hello world"


def test_empty_string():
    assert sanitize("") == ""


@given(
    text=st.text(min_size=0, max_size=200),
)
@settings(max_examples=100)
def test_no_zero_width_in_output(text):
    result = sanitize(text)
    zw_chars = set("\u200b\u200c\u200d\u200e\u200f\ufeff")
    assert not any(c in zw_chars for c in result)


@given(
    text=st.text(min_size=0, max_size=200),
)
@settings(max_examples=100)
def test_no_multiple_spaces(text):
    result = sanitize(text)
    assert "  " not in result


@given(
    text=st.text(min_size=0, max_size=200),
)
@settings(max_examples=100)
def test_no_leading_trailing_whitespace(text):
    result = sanitize(text)
    if result:
        assert result == result.strip()


@given(
    text=st.text(
        min_size=0,
        max_size=100,
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=" "),
    ),
)
@settings(max_examples=50)
def test_normal_text_unchanged(text):
    result = sanitize(text)
    assert result == text.strip() or "  " not in text


@given(
    base=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N"))),
)
@settings(max_examples=50)
def test_zero_width_injection_neutralized(base):
    injected = f"{base}\u200b{base}"
    result = sanitize(injected)
    assert "\u200b" not in result
    assert base in result


def test_tabs_and_newlines_collapsed():
    text = "hello\t\tworld\n\ntest"
    result = sanitize(text)
    assert result == "hello world test"


@given(
    text=st.text(min_size=0, max_size=100),
)
@settings(max_examples=50)
def test_output_always_string(text):
    result = sanitize(text)
    assert isinstance(result, str)
