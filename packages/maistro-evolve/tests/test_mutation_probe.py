"""Diff-scoped mutation probe: strong tests kill introduced-behavior mutants;
weak/under-verifying tests let them survive. Real pytest subprocess runs (no
mocks) against throwaway source+test files, mirroring how the RSI loop scores a
candidate's changed tests against its changed source."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro_evolve.mutation_probe import (
    MutationProbe,
    probe_diff_mutations,
)
from maistro_rsi.contained_validation import ContainmentUnavailable

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


def test_containment_failure_propagates(tmp_path: Path) -> None:
    # A contained read that fails (Docker gone, exec timeout) raises
    # ContainmentUnavailable — a RuntimeError. It must propagate, not be
    # swallowed into an empty plan: an empty plan reports the probe as
    # "unavailable" (skipped), letting an unevaluated candidate pass.
    class _BrokenRunner:
        def read_text(self, rel: str) -> str:
            raise ContainmentUnavailable("docker daemon unreachable")

        def write_text(self, rel: str, content: str) -> None:  # pragma: no cover
            raise AssertionError("never reached")

        def run_tests(
            self, selectors: list[str], *, timeout: int
        ) -> tuple[int, str]:  # pragma: no cover
            raise AssertionError("never reached")

    cwd, selectors = _write(tmp_path, _SOURCE, "def test_noop():\n    assert True\n")
    with pytest.raises(ContainmentUnavailable):
        probe_diff_mutations(cwd, {"source.py": _RETURN_LINE}, selectors, runner=_BrokenRunner())


def test_missing_host_file_is_still_skipped(tmp_path: Path) -> None:
    # Ordinary missing-file handling is preserved: the file is dropped from
    # the plan and the probe reports unavailable (nothing to measure).
    cwd, selectors = _write(tmp_path, _SOURCE, "def test_noop():\n    assert True\n")
    probe = probe_diff_mutations(cwd, {"gone.py": _RETURN_LINE}, selectors)
    assert not probe.available


def test_contained_runner_writes_the_mutant_into_the_tree_it_runs(
    tmp_path: Path,
) -> None:
    """The contained probe's happy path (#614): with a runner, the plan is read
    through it, each mutant is written through it (the tree the tests RUN
    against — the sandbox's copy, never the host worktree), the selectors reach
    the runner's test channel once per mutant, a mutant the tests catch counts
    as killed, and the original bytes are always restored — on the runner's
    tree AND on the host, which never saw the mutant at all."""
    (tmp_path / "source.py").write_text(_SOURCE, encoding="utf-8")

    class _Runner:
        def __init__(self) -> None:
            self.files = {"source.py": _SOURCE}
            self.runs: list[list[str]] = []

        def read_text(self, rel: str) -> str:
            return self.files[rel]

        def write_text(self, rel: str, content: str) -> None:
            self.files[rel] = content

        def run_tests(self, selectors: list[str], *, timeout: int) -> tuple[int, str]:
            self.runs.append(list(selectors))
            # the mutant is in place while this runs: the changed tests fail
            return (1, "1 failed")

    runner = _Runner()
    probe = probe_diff_mutations(
        tmp_path, {"source.py": _RETURN_LINE}, ["test_source.py"], runner=runner
    )

    assert probe.available is True
    assert probe.total >= 1
    assert probe.killed == probe.total
    assert not probe.survivors
    assert runner.runs == [["test_source.py"]] * probe.total
    assert runner.files["source.py"] == _SOURCE, "the runner's tree must be restored"
    host_after = (tmp_path / "source.py").read_text(encoding="utf-8")
    assert host_after == _SOURCE, "the host worktree must never see a mutant"


def test_score_rounds_and_summary_reads() -> None:
    # Pure unit: no subprocess. Two killed of three -> 0.6667.
    probe = MutationProbe(available=True, total=3, killed=2, survived=1, survivors=["m.py:4"])
    assert probe.score == 0.6667
    assert "killed" in probe.summary()
    assert "m.py:4" in probe.summary()
    assert "unavailable" in MutationProbe(available=False).summary()
