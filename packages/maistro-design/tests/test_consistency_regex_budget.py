"""Escaped consistency markers still cannot match without a time budget."""

from __future__ import annotations

import pytest

from maistro_design import consistency


class _ExhaustedPattern:
    def search(self, text: str, *, timeout: float):
        assert timeout > 0
        raise TimeoutError("regex timed out")

    def finditer(self, text: str, *, timeout: float):
        assert timeout > 0
        raise TimeoutError("regex timed out")
        yield  # pragma: no cover — makes this a generator for typing/callers


def test_contains_limits_matching_and_propagates_budget_exhaustion(monkeypatch):
    monkeypatch.setattr(consistency, "_marker_re", lambda pattern: _ExhaustedPattern())
    with pytest.raises(TimeoutError):
        consistency._contains("a+", "aaaa")


def test_affirmative_iteration_limits_total_matching_time(monkeypatch):
    monkeypatch.setattr(consistency, "_marker_re", lambda pattern: _ExhaustedPattern())
    with pytest.raises(TimeoutError):
        consistency._mentions_affirmatively("a+", "aaaa")


@pytest.mark.parametrize("match", [consistency._contains, consistency._mentions_affirmatively])
def test_escaped_markers_remain_literal_under_budgeted_matching(match):
    # Metacharacters match literally (#2288); timeout wiring must not reopen regex.
    assert match("a+", "xaa+yy")
    assert not match("a+", "xaaayy")
    assert match("start your free trial", "Start your free trial")
    assert not match("start your free trial", "Buy now")
    assert match("[invalid", "an [invalid expression")


def test_affirmative_matching_still_honors_negation():
    assert not consistency._mentions_affirmatively("app", "never an app")
    assert consistency._mentions_affirmatively("app", "make an app")


def test_affirmative_returns_before_later_match_budget_work(monkeypatch):
    """First unnegated hit must short-circuit before later finditer work."""

    class _Match:
        def __init__(self, start: int) -> None:
            self._start = start

        def start(self) -> int:
            return self._start

    continued = {"n": 0}

    class _EarlyHitPattern:
        def finditer(self, text: str, *, timeout: float):
            assert timeout > 0
            yield _Match(text.index("app"))
            continued["n"] += 1
            raise TimeoutError("should not consume later matches")

    monkeypatch.setattr(consistency, "_marker_re", lambda pattern: _EarlyHitPattern())
    assert consistency._mentions_affirmatively("app", "make an app then " + ("a" * 200))
    assert continued["n"] == 0


def test_oversized_marker_rejected_before_compile():
    huge = "x" * (consistency._MAX_MARKER_CHARS + 1)
    with pytest.raises(ValueError, match="exceeds"):
        consistency._contains(huge, "x")


@pytest.mark.parametrize("match", [consistency._contains, consistency._mentions_affirmatively])
def test_escaped_adversarial_pattern_does_not_interpret_as_regex(match):
    # Without escaping this would backtrack; escaped it is a literal non-match.
    assert not match(r"(a|aa)+$", "a" * 1000 + "!")
