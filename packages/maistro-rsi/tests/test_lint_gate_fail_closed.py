"""Required static-analysis gates fail closed when their tool cannot run.

#820 (from #304's finding): "No module named bandit" used to emit NO gate at
all — an unavailable required analyzer was indistinguishable from a gate
nobody declared — while the harvest PR body asserted a full pass. These tests
pin the replacement contract: a tool that cannot run yields an explicit
NOT-RUN ``GateResult`` that vetoes promotion, with the cause recorded; a tool
that runs records its provenance (argv, exit code, output digest, version) so
a reviewer can tell a measured pass from everything else.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from maistro_evolve.scorecard import GateResult
from maistro_rsi.candidate_fitness import FitnessInputs, _lint_gates, compose_scorecard

_LINT_GATE_NAMES = ["ruff_clean", "mypy_clean", "no_bandit_high"]


def _write_src(tmp_path: Path) -> list[str]:
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    return ["m.py"]


def _tool_importable(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def test_missing_tool_yields_blocking_not_run_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An interpreter path that cannot exist: every launch fails with
    # FileNotFoundError — the exact "tool missing from the runner" shape.
    monkeypatch.setattr(sys, "executable", "/nonexistent/python-binary")
    gates = _lint_gates(tmp_path, _write_src(tmp_path))
    assert [g.name for g in gates] == _LINT_GATE_NAMES
    for gate in gates:
        assert gate.passed is False
        assert gate.detail.get("not_run") is True
        assert gate.detail.get("cause") == "missing"
        assert "NOT RUN" in gate.reason
        assert gate.detail.get("tool") in {"ruff", "mypy", "bandit"}


def test_unimportable_tool_yields_blocking_not_run_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The exact production shape from #304: the runner answers every
    # `<tool>` import with "No module named ..." — the gate must say the tool
    # did not run, not silently vanish.
    fake = tmp_path / "fake-python"
    fake.write_text("#!/bin/sh\necho 'No module named bandit' >&2\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(fake))
    gates = _lint_gates(tmp_path, _write_src(tmp_path))
    assert [g.name for g in gates] == _LINT_GATE_NAMES
    for gate in gates:
        assert gate.passed is False
        assert gate.detail.get("not_run") is True
        assert gate.detail.get("cause") == "module_missing"


def test_not_run_lint_gate_blocks_promotion() -> None:
    # AC-3 (blocking half): a missing gate tool must veto the candidate —
    # the scorecard rejects, the composite is 0, and the failing gate's
    # reason identifies the state as NOT RUN (not a measured failure).
    not_run_bandit = GateResult(
        "no_bandit_high",
        False,
        "NOT RUN: bandit unavailable (missing) — required gate fails closed",
        detail={"tool": "bandit", "not_run": True, "cause": "missing"},
    )
    scorecard = compose_scorecard(FitnessInputs(tests_passed=True, lint_gates=[not_run_bandit]))
    assert scorecard.accepted is False
    assert scorecard.composite == 0.0
    gate = next(g for g in scorecard.gates if g.name == "no_bandit_high")
    assert gate.passed is False
    assert "NOT RUN" in gate.reason


def test_no_source_files_declares_no_lint_gate(tmp_path: Path) -> None:
    # Nothing changed that these gates could measure — none is declared, and
    # nothing downstream may render their absence as a pass (the harvest body
    # states only recorded gates; see test_harvest.py).
    assert _lint_gates(tmp_path, []) == []


@pytest.mark.skipif(not _tool_importable("ruff"), reason="ruff not installed in this environment")
def test_ran_gate_records_provenance(tmp_path: Path) -> None:
    # AC-5 (measured half): a gate whose tool ran records exact provenance —
    # argv, exit code, output digest — so a reviewer can distinguish this
    # from an unavailable/skipped gate.
    gates = _lint_gates(tmp_path, _write_src(tmp_path))
    ruff = next(g for g in gates if g.name == "ruff_clean")
    assert ruff.passed is True
    assert ruff.detail.get("not_run", False) is False
    assert ruff.detail.get("exit_code") == 0
    argv = ruff.detail.get("argv")
    assert isinstance(argv, list) and any("ruff" in str(part) for part in argv)
    digest = ruff.detail.get("output_digest")
    assert isinstance(digest, str) and len(digest) == 12
    version = ruff.detail.get("version")
    assert isinstance(version, str) and version  # e.g. "ruff 0.x.y"
