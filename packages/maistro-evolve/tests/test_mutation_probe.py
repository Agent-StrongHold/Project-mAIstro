"""Diff-scoped mutation probe: strong tests kill introduced-behavior mutants;
weak/under-verifying tests let them survive. Real pytest subprocess runs (no
mocks) against throwaway source+test files, mirroring how the RSI loop scores a
candidate's changed tests against its changed source."""

from __future__ import annotations

from pathlib import Path

from maistro_evolve.mutation_probe import (
    MutationProbe,
    probe_diff_mutations,
)

# combine(a, b) == a * b + 1 — three mutable sites on the return line:
# Mult->Add, Add->Sub, and the constant 1->2.
_SOURCE = """def combine(a, b):
    return a * b + 1
"""
_RETURN_LINE = {2}


def _write(tmp_path: Path, source_body: str, test_body: str) -> tuple[Path, list[str]]:
    (tmp_path / "source.py").write_text(source_body, encoding="utf-8")
    (tmp_path / "test_source.py").write_text(test_body, encoding="utf-8")
    return tmp_path, ["test_source.py"]


def test_strong_tests_kill_every_mutant(tmp_path: Path) -> None:
    # Inputs chosen so each operator/constant mutation changes the result.
    tests = (
        "from source import combine\n"
        "def test_combine():\n"
        "    assert combine(2, 3) == 7\n"
        "    assert combine(3, 4) == 13\n"
        "    assert combine(0, 5) == 1\n"
    )
    cwd, selectors = _write(tmp_path, _SOURCE, tests)
    probe = probe_diff_mutations(cwd, {"source.py": _RETURN_LINE}, selectors, timeout=60)
    assert probe.available
    assert probe.total == 3
    assert probe.survived == 0
    assert probe.score == 1.0


def test_weak_test_lets_mutants_survive(tmp_path: Path) -> None:
    # A smoke test that never pins the value — every mutant still returns non-None,
    # so nothing is killed. This is the reward-hacking signature the gate exists
    # to catch: tests pass, but they do not constrain the behavior.
    tests = "from source import combine\ndef test_smoke():\n    assert combine(2, 3) is not None\n"
    cwd, selectors = _write(tmp_path, _SOURCE, tests)
    probe = probe_diff_mutations(cwd, {"source.py": _RETURN_LINE}, selectors, timeout=60)
    assert probe.available
    assert probe.total == 3
    assert probe.killed == 0
    assert probe.score == 0.0
    assert probe.survivors  # each survivor names the file:line it slipped through


def test_no_tests_is_unavailable(tmp_path: Path) -> None:
    cwd, _ = _write(tmp_path, _SOURCE, "def test_noop():\n    assert True\n")
    probe = probe_diff_mutations(cwd, {"source.py": _RETURN_LINE}, [], timeout=60)
    assert probe.available is False
    assert probe.score == 0.0


def test_no_mutable_lines_is_unavailable(tmp_path: Path) -> None:
    # Targeting a line with no mutable AST site (the def header) measures nothing.
    tests = "from source import combine\ndef test_c():\n    assert combine(1, 1) == 2\n"
    cwd, selectors = _write(tmp_path, _SOURCE, tests)
    probe = probe_diff_mutations(cwd, {"source.py": {1}}, selectors, timeout=60)
    assert probe.available is False


def test_source_is_restored_after_probe(tmp_path: Path) -> None:
    tests = "from source import combine\ndef test_c():\n    assert combine(1, 1) == 2\n"
    cwd, selectors = _write(tmp_path, _SOURCE, tests)
    probe_diff_mutations(cwd, {"source.py": _RETURN_LINE}, selectors, timeout=60)
    assert (cwd / "source.py").read_text(encoding="utf-8") == _SOURCE


def test_max_mutants_caps_the_run(tmp_path: Path) -> None:
    tests = (
        "from source import combine\n"
        "def test_combine():\n"
        "    assert combine(2, 3) == 7\n"
        "    assert combine(3, 4) == 13\n"
    )
    cwd, selectors = _write(tmp_path, _SOURCE, tests)
    probe = probe_diff_mutations(
        cwd, {"source.py": _RETURN_LINE}, selectors, timeout=60, max_mutants=1
    )
    assert probe.total == 1


def test_score_rounds_and_summary_reads() -> None:
    # Pure unit: no subprocess. Two killed of three -> 0.6667.
    probe = MutationProbe(available=True, total=3, killed=2, survived=1, survivors=["m.py:4"])
    assert probe.score == 0.6667
    assert "killed" in probe.summary()
    assert "m.py:4" in probe.summary()
    assert "unavailable" in MutationProbe(available=False).summary()
