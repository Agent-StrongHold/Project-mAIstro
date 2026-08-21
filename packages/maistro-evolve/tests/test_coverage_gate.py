"""Tests for the coverage gate/score (subprocess stubbed — no real test run)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import maistro_evolve.coverage_gate as cg


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def test_gate_fails_when_coverage_drops() -> None:
    g = cg.coverage_gate(80.0, 70.0)
    assert g.passed is False
    assert "70.0" in g.reason


def test_gate_passes_within_tolerance_or_improved() -> None:
    assert cg.coverage_gate(80.0, 79.7).passed is True  # within 0.5 tol
    assert cg.coverage_gate(80.0, 85.0).passed is True  # improved


def test_gate_not_enforced_when_coverage_unavailable() -> None:
    assert cg.coverage_gate(None, 80.0).passed is True
    assert cg.coverage_gate(80.0, None).passed is True


def test_coverage_signal_scores_the_delta_not_the_absolute() -> None:
    # Reward the direction of the move: flat is neutral, a gain trends to 1.0, a
    # drop toward 0.0 — so a restyle (flat) no longer scores the suite's standing
    # coverage like every other candidate.
    assert cg.coverage_signal(60.0, 60.0, 0.2).score == 0.5  # flat → neutral
    assert cg.coverage_signal(60.0, 61.0, 0.2).score == 0.75  # +1pp over a 2pp swing
    assert cg.coverage_signal(60.0, 75.0, 0.2).score == 1.0  # big gain → clamped 1.0
    assert cg.coverage_signal(60.0, 55.0, 0.2).score == 0.0  # drop → clamped 0.0
    s = cg.coverage_signal(60.0, 75.0, 0.2)
    assert "+15.0pp" in s.rationale
    assert s.detail["delta"] == 15.0


def test_measure_coverage_parses_totals(monkeypatch) -> None:
    class R:
        returncode = 0
        stdout = json.dumps({"totals": {"percent_covered": 87.5}})

    monkeypatch.setattr(cg.subprocess, "run", lambda *a, **k: R())
    assert cg.measure_coverage(".") == 87.5


def test_measure_coverage_none_on_unparseable(monkeypatch) -> None:
    class R:
        returncode = 0
        stdout = "not json at all"

    monkeypatch.setattr(cg.subprocess, "run", lambda *a, **k: R())
    assert cg.measure_coverage(".") is None


def test_new_source_lines_finds_added_lines(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.co")
    _git(repo, "config", "user.name", "t")
    (repo / "m.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "base")
    (repo / "m.py").write_text(
        "def a():\n    return 1\n\n\ndef b():\n    return 2\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "candidate")

    added = cg.new_source_lines(repo, "base", ["m.py"])
    assert "m.py" in added
    # The new def b(): return 2 body — exact line numbers depend on the diff,
    # but there must be new lines recorded and none from the untouched def a().
    assert added["m.py"]
    assert 1 not in added["m.py"] and 2 not in added["m.py"]


def test_new_source_lines_empty_when_file_unchanged(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.co")
    _git(repo, "config", "user.name", "t")
    (repo / "m.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "base")

    assert cg.new_source_lines(repo, "base", ["m.py"]) == {}


def test_uncovered_new_lines_intersects_added_and_missing() -> None:
    new_lines = {"m.py": {5, 6, 7}, "n.py": {10}}
    missing = {"m.py": [6, 20, 21], "n.py": []}
    result = cg.uncovered_new_lines(new_lines, missing)
    assert result == {"m.py": [6]}  # only the intersection; n.py fully covered


def test_uncovered_new_lines_empty_when_all_covered() -> None:
    new_lines = {"m.py": {5, 6}}
    missing = {"m.py": [100]}
    assert cg.uncovered_new_lines(new_lines, missing) == {}
