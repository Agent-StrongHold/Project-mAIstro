"""Caller-authored regexes retain their syntax but cannot run without a budget."""

import pytest
import regex

from maistro_design import consistency


def test_contains_limits_matching_and_propagates_budget_exhaustion(monkeypatch):
    def exhausted(pattern, text, flags=0, *, timeout):
        assert timeout > 0
        raise TimeoutError("regex timed out")

    monkeypatch.setattr(regex, "search", exhausted)
    with pytest.raises(TimeoutError):
        consistency._contains("a+", "aaaa")


def test_affirmative_iteration_limits_total_matching_time(monkeypatch):
    class ExhaustedPattern:
        def finditer(self, text, *, timeout):
            assert timeout > 0
            raise TimeoutError("regex timed out")

    monkeypatch.setattr(regex, "compile", lambda *args, **kwargs: ExhaustedPattern())
    with pytest.raises(TimeoutError):
        consistency._mentions_affirmatively("a+", "aaaa")


@pytest.mark.parametrize("match", [consistency._contains, consistency._mentions_affirmatively])
def test_regex_syntax_and_invalid_literal_fallback_are_preserved(match):
    assert match(r"start your (free )?trial", "Start your free trial")
    assert match(r"start your (free )?trial", "Start your trial")
    assert not match(r"start your (free )?trial", "Buy now")
    assert match("[invalid", "an [invalid expression")


def test_affirmative_matching_still_honors_negation():
    assert not consistency._mentions_affirmatively("app", "never an app")
    assert consistency._mentions_affirmatively("app", "make an app")


@pytest.mark.parametrize("match", [consistency._contains, consistency._mentions_affirmatively])
def test_adversarial_backtracking_exhausts_budget_without_a_verdict(match):
    with pytest.raises(TimeoutError):
        match(r"(a|aa)+$", "a" * 1000 + "!")
