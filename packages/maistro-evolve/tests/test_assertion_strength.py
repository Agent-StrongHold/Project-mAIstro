"""Tests for the assertion-strength AST metric."""

from __future__ import annotations

from pathlib import Path

from maistro_evolve.assertion_strength import score_assertions


def _score(tmp_path: Path, code: str):
    f = tmp_path / "t.py"
    f.write_text(code, encoding="utf-8")
    return score_assertions(f)


def test_exact_value_assertion_scores_strong(tmp_path: Path) -> None:
    s = _score(tmp_path, "def test_a():\n    x = 41 + 1\n    assert x == 42\n")
    assert s.score == 1.0
    assert s.strong == 1


def test_weak_assertions_score_low(tmp_path: Path) -> None:
    s = _score(
        tmp_path,
        "def test_a():\n    assert f() is not None\n\ndef test_b():\n    assert g()\n",
    )
    assert s.score is not None and s.score <= 0.3
    assert s.weak == 2


def test_test_with_no_assertion_is_vacuous(tmp_path: Path) -> None:
    assert _score(tmp_path, "def test_a():\n    do_something()\n").score == 0.0


def test_assert_true_is_vacuous(tmp_path: Path) -> None:
    assert _score(tmp_path, "def test_a():\n    assert True\n").score == 0.0


def test_assert_equals_true_is_weak_not_strong(tmp_path: Path) -> None:
    s = _score(tmp_path, "def test_a():\n    assert flag == True\n")
    assert s.score == 0.3


def test_pytest_raises_counts_as_strong_ish(tmp_path: Path) -> None:
    code = "import pytest\n\ndef test_a():\n    with pytest.raises(ValueError):\n        f()\n"
    assert _score(tmp_path, code).score >= 0.8


def test_non_test_file_returns_none(tmp_path: Path) -> None:
    assert _score(tmp_path, "def helper():\n    return 1\n").score is None
