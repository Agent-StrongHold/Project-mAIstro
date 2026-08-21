"""Composition/normalisation tests for the code-quality composite.

The tool subprocesses (ruff/bandit/mypy/radon) are stubbed, so these run
deterministically without the tools installed — they exercise the weighting,
missing-tool renormalisation, and score plumbing, not the tools themselves.
"""

from __future__ import annotations

from pathlib import Path

import maistro_evolve.code_quality as cq


def _stub(
    monkeypatch,
    *,
    ruff,
    bandit,
    mypy,
    radon,
    pylint=(1.0, 10.0),
    docstrings=(1.0, 100.0),
    halstead=(1.0, 0.0),
    type_coverage=(1.0, 100.0),
    duplication=(1.0, 0.0),
    dead_code=(1.0, 0),
    cognitive=(1.0, 1.0),
    semgrep=(None, 0),
):
    monkeypatch.setattr(cq, "_ruff", lambda p: ruff)
    monkeypatch.setattr(cq, "_bandit", lambda p: bandit)
    monkeypatch.setattr(cq, "_mypy", lambda p: mypy)
    monkeypatch.setattr(cq, "_pylint", lambda p: pylint)
    monkeypatch.setattr(cq, "_docstring_coverage", lambda p: docstrings)
    monkeypatch.setattr(cq, "_halstead", lambda p: halstead)
    monkeypatch.setattr(cq, "_type_coverage", lambda p: type_coverage)
    monkeypatch.setattr(cq, "_duplication", lambda p: duplication)
    monkeypatch.setattr(cq, "_dead_code", lambda p: dead_code)
    monkeypatch.setattr(cq, "_cognitive", lambda p: cognitive)
    monkeypatch.setattr(cq, "_semgrep", lambda p: semgrep)
    monkeypatch.setattr(cq, "_radon", lambda p: radon)


def test_perfect_code_scores_one(monkeypatch, tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("x = 1\n")
    _stub(monkeypatch, ruff=(1.0, 0), bandit=(1.0, 0), mypy=(1.0, 0), radon=(1.0, 1.0, 1.0, 100.0))
    assert cq.score_path(f).composite == 1.0


def test_bad_code_scores_low(monkeypatch, tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("x = 1\n")
    _stub(
        monkeypatch,
        ruff=(0.1, 9),
        bandit=(0.2, 3),
        mypy=(0.5, 1),
        radon=(0.7, 0.6, 12.0, 60.0),
        pylint=(0.4, 4.0),
        docstrings=(0.2, 20.0),
        halstead=(0.5, 15.0),
        type_coverage=(0.3, 30.0),
        duplication=(0.6, 40.0),
        dead_code=(0.5, 1),
        cognitive=(0.4, 20.0),
    )
    s = cq.score_path(f)
    assert s.composite < 0.6
    assert s.bandit_issues == 3
    assert s.ruff_violations == 9
    assert s.pylint == 0.4
    assert s.docstrings == 0.2


def test_graded_metrics_spread_between_good_and_great(monkeypatch, tmp_path: Path) -> None:
    # All defect floors clean (1.0) but graded metrics differ -> composite differs,
    # which is the whole point: the score doesn't saturate at 1.0 for clean code.
    f = tmp_path / "x.py"
    f.write_text("x = 1\n")
    clean = {
        "ruff": (1.0, 0),
        "bandit": (1.0, 0),
        "mypy": (1.0, 0),
        "radon": (1.0, 1.0, 1.0, 100.0),
    }
    _stub(monkeypatch, **clean, pylint=(1.0, 10.0), docstrings=(1.0, 100.0), halstead=(1.0, 1.0))
    great = cq.score_path(f).composite
    _stub(monkeypatch, **clean, pylint=(0.85, 8.5), docstrings=(0.4, 40.0), halstead=(0.7, 6.0))
    good = cq.score_path(f).composite
    assert great == 1.0
    assert good < great  # graded metrics pull a merely-clean file below 1.0


def test_missing_tool_renormalises_weights(monkeypatch, tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("x = 1\n")
    # mypy unavailable -> dropped; composite is the mean of the rest (all 1.0).
    _stub(monkeypatch, ruff=(1.0, 0), bandit=(1.0, 0), mypy=(None, 0), radon=(1.0, 1.0, 1.0, 100.0))
    s = cq.score_path(f)
    assert s.composite == 1.0
    assert "mypy" in s.tools_missing
    assert s.mypy is None


def test_all_tools_missing_scores_zero(monkeypatch, tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("x = 1\n")
    _stub(
        monkeypatch,
        ruff=(None, 0),
        bandit=(None, 0),
        mypy=(None, 0),
        radon=(None, None, 0.0, 0.0),
        pylint=(None, 0.0),
        docstrings=(None, 0.0),
        halstead=(None, 0.0),
        type_coverage=(None, 0.0),
        duplication=(None, 0.0),
        dead_code=(None, 0),
        cognitive=(None, 0.0),
        semgrep=(None, 0),
    )
    s = cq.score_path(f)
    assert s.composite == 0.0
    # semgrep has weight 0, so a missing semgrep is not reported.
    assert set(s.tools_missing) == {
        "ruff",
        "bandit",
        "mypy",
        "pylint",
        "docstrings",
        "halstead",
        "type_coverage",
        "duplication",
        "dead_code",
        "cognitive",
        "radon_cc",
        "radon_mi",
    }
