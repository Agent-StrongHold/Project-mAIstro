"""Red→green as a *signal*, not a gate — because the real gate is coverage.

Red→green (a changed test fails on baseline, passes on candidate) is a nice
positive marker that a change was test-first. But it must NOT be a veto: two
perfectly valid moves are green-on-baseline and would be wrongly rejected by a
red→green gate —

  - **refactor** — green→green, no test change (improve maintainability/DRY/CC
    while behaviour is preserved); rewarded by the code-quality delta.
  - **characterization test** — add a test to already-correct code. It passes on
    baseline (not red→green) but raises coverage — valuable, not vacuous.

What red→green was really guarding against — untested code sneaking in — is
already caught by **coverage not dropping** (see `coverage_gate`), which is the
universal gate together with "tests pass". So this module offers red→green only
as a small positive `SignalScore` (reward test-first behaviour; never punish the
absence of it). `run_test_selection()` produces the `TddEvidence` the loop fills.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from maistro_evolve.scorecard import MeasureKind, SignalScore

_TEST_HINTS = ("test_", "_test.py", "/tests/", "conftest.py")


def changed_test_paths(changed_paths: list[str]) -> list[str]:
    """Filter a diff's changed paths down to the ones that are tests."""
    return [p for p in changed_paths if any(h in p.replace("\\", "/") for h in _TEST_HINTS)]


@dataclass
class TddEvidence:
    changed_tests: list[str] = field(default_factory=list)
    # Exit code of running the *changed* tests against each code state.
    baseline_changed_rc: int | None = None  # expect non-zero (red) when tests changed
    candidate_changed_rc: int | None = None  # expect zero (green)
    # Whole-suite failing counts, for the "fixed a pre-existing failing test" mode.
    baseline_suite_failures: int = 0
    candidate_suite_failures: int = 0


def red_green_signal(evidence: TddEvidence, weight: float = 0.05) -> SignalScore:
    """A small positive reward for demonstrably test-first change — never a veto.

    - 1.0: a changed test was red on baseline and green on candidate (test-first,
      bug-fix, or strengthened-assertion), OR a previously-failing test went green.
    - 0.5: green→green (refactor) or a characterization test — valid, just not
      test-first; not punished (its reward comes from code-quality/coverage).
    The safety gate is coverage-not-dropped + tests-pass, elsewhere; this only
    nudges the fitness toward genuine TDD when several candidates are otherwise
    comparable.
    """
    ev = evidence
    test_first = (
        ev.changed_tests
        and ev.baseline_changed_rc not in (None, 0)
        and ev.candidate_changed_rc == 0
    )
    fixed_failing = ev.candidate_suite_failures < ev.baseline_suite_failures
    if test_first:
        score, why = 1.0, f"{len(ev.changed_tests)} changed test(s): red on baseline → green"
    elif fixed_failing:
        n = ev.baseline_suite_failures - ev.candidate_suite_failures
        score, why = 1.0, f"turned {n} previously-failing test(s) green"
    else:
        score, why = 0.5, "not test-first (refactor / characterization) — valid, not penalised"
    return SignalScore(
        name="red_green",
        kind=MeasureKind.CALCULATED,
        score=score,
        weight=weight,
        rationale=why,
    )


def _count_test_functions(source: str) -> int:
    """Count ``test_*`` functions/methods in Python ``source`` (0 on a parse error)."""
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def count_net_new_tests(repo_dir: str | Path, baseline_ref: str, test_files: list[str]) -> int:
    """Net increase in ``test_*`` functions across ``test_files`` vs ``baseline_ref``.

    Candidate count minus baseline count (floored at 0): a genuinely added test
    raises it; a rename or edit-in-place leaves it at 0. Baseline is read with
    ``git show`` (a file absent on baseline counts as 0 → all its tests are new).
    """
    cwd = Path(repo_dir)
    net = 0
    for rel in test_files:
        try:
            candidate = (cwd / rel).read_text(encoding="utf-8")
        except OSError:
            candidate = ""
        base = subprocess.run(
            ["git", "show", f"{baseline_ref}:{rel}"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        baseline_src = base.stdout if base.returncode == 0 else ""
        net += max(0, _count_test_functions(candidate) - _count_test_functions(baseline_src))
    return net


def new_test_signal(
    net_new_tests: int,
    coverage_delta: float | None,
    weight: float,
    *,
    uncovered_new_lines: dict[str, list[int]] | None = None,
) -> SignalScore | None:
    """Reward a genuinely new, coverage-raising test — or return ``None`` (absent).

    Fires only when a net-new ``test_*`` was added **and** coverage rose, so the
    signal is present exactly for substantive test work. Because ``composite``
    renormalises over present signals, its presence lifts a test-adding candidate
    well above a docstring-only one (which lacks it), and its absence never
    dilutes a non-test candidate. The passing gate stays "tests_pass" elsewhere.

    ``uncovered_new_lines`` (from ``coverage_gate.uncovered_new_lines``) guards
    against a project-wide coverage delta hiding an untested part of THIS diff:
    if the candidate added source lines that its own coverage run never
    executed, the signal withholds credit even though an unrelated test in the
    same diff raised the aggregate percentage — otherwise a well-tested change
    can carry an untested one to a positive composite for free.
    """
    if net_new_tests <= 0 or coverage_delta is None or coverage_delta <= 0:
        return None
    if uncovered_new_lines:
        return None
    return SignalScore(
        name="new_test",
        kind=MeasureKind.CALCULATED,
        score=1.0,
        weight=weight,
        rationale=f"{net_new_tests} net-new green test(s); coverage +{coverage_delta:.1f}pp",
    )


def run_test_selection(
    repo_dir: str | Path, selectors: list[str], *, timeout: int = 600
) -> tuple[int, str]:
    """Run pytest on specific files/selectors in ``repo_dir``; return (exit_code, output).

    Used by the loop to build TddEvidence: run the candidate's changed tests
    against a baseline checkout (expect non-zero) and the candidate (expect zero).
    """
    # PYTHONDONTWRITEBYTECODE: red->green reverts a source file between two runs,
    # often within the same second — a cached .pyc would make the baseline run
    # reuse the candidate's bytecode and wrongly pass. -p no:cacheprovider drops
    # pytest's own cache too.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *selectors],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, "test run failed to execute"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
