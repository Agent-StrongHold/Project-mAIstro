"""Integration tests for the new hard gates' helper functions: real files on
disk, real ``ast.parse``/pytest subprocess calls — the exact mechanism that let
a syntax-broken, misplaced test file (packages/maistro_rsi/src/.../test_scout.py
with a literal ``<ImprovementKind.new_test: 'new_test'>`` in a dict) slip
through a live run undetected."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from maistro_evolve.tdd_gate import TddEvidence
from maistro_rsi.candidate_fitness import (
    _parse_test_roots,
    _syntax_check,
    _uncollectable_tests,
    _vacuous_test_reasons,
)

_PYTEST_RUNNABLE = (
    subprocess.run([sys.executable, "-m", "pytest", "--version"], capture_output=True).returncode
    == 0
)


def test_syntax_check_flags_invalid_python(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text(
        "def f():\n    return {'k': <NotAThing: 'x'>}\n", encoding="utf-8"
    )
    reasons = _syntax_check(tmp_path, ["good.py", "bad.py"])
    assert len(reasons) == 1
    assert "bad.py" in reasons[0]


def test_syntax_check_empty_when_all_valid(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    assert _syntax_check(tmp_path, ["a.py", "b.py"]) == []


def test_syntax_check_skips_missing_files(tmp_path: Path) -> None:
    # A file the diff deleted shouldn't be checked (nothing to parse).
    assert _syntax_check(tmp_path, ["gone.py"]) == []


def test_parse_test_roots_extracts_paths_and_drops_flags() -> None:
    args = "packages/maistro-evolve/tests packages/maistro-rsi/tests --ignore=x/y -q"
    assert _parse_test_roots(args) == [
        "packages/maistro-evolve/tests",
        "packages/maistro-rsi/tests",
    ]


def test_parse_test_roots_empty_string() -> None:
    assert _parse_test_roots("") == []


@pytest.mark.skipif(not _PYTEST_RUNNABLE, reason="pytest not runnable as a subprocess")
def test_uncollectable_flags_file_outside_configured_roots(tmp_path: Path) -> None:
    # Mirrors the real bug: a test written under src/ instead of tests/.
    src_test = tmp_path / "packages" / "demo" / "src" / "demo" / "test_x.py"
    src_test.parent.mkdir(parents=True)
    src_test.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    valid_roots = ["packages/demo/tests"]
    reasons = _uncollectable_tests(tmp_path, ["packages/demo/src/demo/test_x.py"], valid_roots)
    assert len(reasons) == 1
    assert "outside configured test roots" in reasons[0]


@pytest.mark.skipif(not _PYTEST_RUNNABLE, reason="pytest not runnable as a subprocess")
def test_uncollectable_flags_syntax_broken_test_even_inside_roots(tmp_path: Path) -> None:
    # The exact real-world case: valid location, but pytest can't collect it.
    tests_dir = tmp_path / "packages" / "demo" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_broken.py").write_text(
        "def test_x():\n    assert {'k': <NotAThing: 'v'>}\n", encoding="utf-8"
    )
    reasons = _uncollectable_tests(
        tmp_path, ["packages/demo/tests/test_broken.py"], ["packages/demo/tests"]
    )
    assert len(reasons) == 1
    assert "could not collect" in reasons[0]


@pytest.mark.skipif(not _PYTEST_RUNNABLE, reason="pytest not runnable as a subprocess")
def test_uncollectable_passes_a_real_collectable_test(tmp_path: Path) -> None:
    tests_dir = tmp_path / "packages" / "demo" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    reasons = _uncollectable_tests(
        tmp_path, ["packages/demo/tests/test_ok.py"], ["packages/demo/tests"]
    )
    assert reasons == []


def test_uncollectable_no_roots_configured_skips_location_check(tmp_path: Path) -> None:
    # Empty valid_roots (e.g. a bare `pytest` with no scoped args) means every
    # location is acceptable — only collectability itself is checked.
    (tmp_path / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    reasons = _uncollectable_tests(tmp_path, ["test_x.py"], [])
    assert reasons == []


def test_vacuous_test_reasons_fires_when_src_changed_but_test_still_green_on_revert() -> None:
    tdd = TddEvidence(changed_tests=["test_x.py"], baseline_changed_rc=0, candidate_changed_rc=0)
    reasons = _vacuous_test_reasons(["src.py"], ["test_x.py"], tdd)
    assert len(reasons) == 1
    assert "doesn't exercise" in reasons[0]


def test_vacuous_test_reasons_absent_for_genuine_characterization_test() -> None:
    # No source change in the diff at all (src=[]) — baseline_changed_rc is
    # never computed for this case (see _red_green_evidence), so this must not
    # be flagged as vacuous.
    tdd = TddEvidence(changed_tests=["test_x.py"], baseline_changed_rc=None, candidate_changed_rc=0)
    assert _vacuous_test_reasons([], ["test_x.py"], tdd) == []


def test_vacuous_test_reasons_absent_for_genuine_red_green() -> None:
    tdd = TddEvidence(changed_tests=["test_x.py"], baseline_changed_rc=1, candidate_changed_rc=0)
    assert _vacuous_test_reasons(["src.py"], ["test_x.py"], tdd) == []
