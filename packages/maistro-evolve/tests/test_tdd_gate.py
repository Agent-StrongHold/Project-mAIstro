"""Tests for the red->green signal (a bonus, never a veto)."""

from __future__ import annotations

from maistro_evolve.scorecard import MeasureKind
from maistro_evolve.tdd_gate import TddEvidence, changed_test_paths, red_green_signal


def test_changed_test_paths_filters_tests() -> None:
    paths = [
        "src/foo.py",
        "packages/x/tests/test_foo.py",
        "src/bar_test.py",
        "conftest.py",
        "README.md",
    ]
    assert changed_test_paths(paths) == [
        "packages/x/tests/test_foo.py",
        "src/bar_test.py",
        "conftest.py",
    ]


def test_test_first_red_then_green_scores_full() -> None:
    ev = TddEvidence(changed_tests=["test_x.py"], baseline_changed_rc=1, candidate_changed_rc=0)
    s = red_green_signal(ev)
    assert s.score == 1.0
    assert s.kind is MeasureKind.CALCULATED


def test_fixing_failing_test_scores_full() -> None:
    ev = TddEvidence(changed_tests=[], baseline_suite_failures=3, candidate_suite_failures=1)
    assert red_green_signal(ev).score == 1.0


def test_refactor_is_not_penalised_below_neutral() -> None:
    # green->green, no test change: valid refactor -> neutral, NEVER a veto.
    ev = TddEvidence(changed_tests=[], baseline_suite_failures=0, candidate_suite_failures=0)
    assert red_green_signal(ev).score == 0.5


def test_characterization_test_green_on_baseline_is_neutral() -> None:
    # A new test that passes on baseline (tests already-correct code) is valid,
    # not vacuous — it raises coverage. Just not test-first, so neutral.
    ev = TddEvidence(changed_tests=["test_x.py"], baseline_changed_rc=0, candidate_changed_rc=0)
    assert red_green_signal(ev).score == 0.5
