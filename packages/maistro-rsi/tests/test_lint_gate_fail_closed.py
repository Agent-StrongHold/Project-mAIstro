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
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maistro_evolve.scorecard import GateResult
from maistro_rsi.candidate_fitness import (
    FitnessInputs,
    _bandit_judgement,
    _lint_gates,
    _mypy_judgement,
    _ruff_judgement,
    _tool_version,
    compose_scorecard,
)

_LINT_GATE_NAMES = ["ruff_clean", "mypy_clean", "no_bandit_high"]


def _proc(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["tool"], returncode=returncode, stdout=stdout, stderr=stderr
    )


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


def test_wedged_tool_yields_blocking_not_run_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A tool that hangs past its budget must not wedge the loop AND must not
    # read as a pass: the gate records the wedge as an explicit NOT RUN veto.
    def wedge(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="tool", timeout=120)

    monkeypatch.setattr(subprocess, "run", wedge)
    gates = _lint_gates(tmp_path, _write_src(tmp_path))
    assert [g.name for g in gates] == _LINT_GATE_NAMES
    for gate in gates:
        assert gate.passed is False
        assert gate.detail.get("not_run") is True
        assert gate.detail.get("cause") == "timeout"
        assert "NOT RUN" in gate.reason


def test_unlaunchable_tool_yields_blocking_not_run_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An OS-level launch failure that is not a missing file (e.g. a
    # non-executable interpreter path) is also a NOT RUN veto, with the OS
    # error recorded as the cause — never an omitted gate.
    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError("exec format refuses us")

    monkeypatch.setattr(subprocess, "run", refuse)
    gates = _lint_gates(tmp_path, _write_src(tmp_path))
    assert [g.name for g in gates] == _LINT_GATE_NAMES
    for gate in gates:
        assert gate.passed is False
        assert gate.detail.get("not_run") is True
        assert gate.detail.get("cause", "").startswith("launch_error:")


def test_ruff_judgement_counts_findings_and_tolerates_unparseable_output() -> None:
    # A tool that RAN but emitted something unparseable is judged on what it
    # said (nothing parseable = no counted violations), never treated as a
    # not-run — the not_run classification belongs to tools that didn't run.
    passed, reason = _ruff_judgement(_proc(stdout=json.dumps([{"code": "E1"}, {"code": "E2"}])))
    assert (passed, reason) == (False, "2 lint violation(s)")
    clean, clean_reason = _ruff_judgement(_proc(stdout="[]"))
    assert (clean, clean_reason) == (True, "0 lint violation(s)")
    fallback, fallback_reason = _ruff_judgement(_proc(stdout="<not json>"))
    assert (fallback, fallback_reason) == (True, "0 lint violation(s)")


def test_mypy_judgement_counts_error_lines() -> None:
    ok, ok_reason = _mypy_judgement(_proc(stdout="Success: no issues found\n"))
    assert (ok, ok_reason) == (True, "0 type error(s)")
    bad, bad_reason = _mypy_judgement(
        _proc(stdout="m.py:1: error: bad thing [misc]\nm.py:2: error: worse [name-defined]\n")
    )
    assert (bad, bad_reason) == (False, "2 type error(s)")


def test_bandit_judgement_fails_only_on_high_severity() -> None:
    # The gate's contract is HIGH-severity findings; a ran-tool judgement must
    # count them from the tool's JSON, and an unparseable report counts as
    # nothing found (the tool ran; it is not a not_run).
    high = _bandit_judgement(
        _proc(stdout=json.dumps({"results": [{"issue_severity": "HIGH", "test_id": "B1"}]}))
    )
    assert high == (False, "1 HIGH-severity finding(s)")
    medium = _bandit_judgement(
        _proc(stdout=json.dumps({"results": [{"issue_severity": "MEDIUM", "test_id": "B2"}]}))
    )
    assert medium == (True, "0 HIGH-severity finding(s)")
    unparseable = _bandit_judgement(_proc(stdout="<<truncated>>"))
    assert unparseable == (True, "0 HIGH-severity finding(s)")


def test_tool_version_probes_the_tool_head_not_the_full_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The probe must reuse the invocation's head (interpreter, -m, tool) —
    # appending --version to `ruff check …` would query nothing.
    seen: list[list[str]] = []

    def capture(probe: list[str], *args: object, **kwargs: object):
        seen.append(probe)
        return _proc(stdout="ruff 0.13.0\n")

    monkeypatch.setattr(subprocess, "run", capture)
    version = _tool_version(
        ["python", "-m", "ruff", "check", "--output-format", "json", "m.py"], tmp_path
    )
    assert version == "ruff 0.13.0"
    assert seen == [["python", "-m", "ruff", "--version"]]


def test_tool_version_is_none_when_the_tool_wont_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Provenance is recorded when available, never invented: a failing,
    # wedged, unlaunchable, or silent --version probe records no version —
    # the gate still records its measured result.
    def failing(probe: list[str], *args: object, **kwargs: object):
        return _proc(returncode=2)

    monkeypatch.setattr(subprocess, "run", failing)
    assert _tool_version(["python", "-m", "ruff"], tmp_path) is None

    def wedged(probe: list[str], *args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="probe", timeout=30)

    monkeypatch.setattr(subprocess, "run", wedged)
    assert _tool_version(["python", "-m", "ruff"], tmp_path) is None

    def unlaunchable(probe: list[str], *args: object, **kwargs: object) -> None:
        raise PermissionError("no")

    monkeypatch.setattr(subprocess, "run", unlaunchable)
    assert _tool_version(["python", "-m", "ruff"], tmp_path) is None

    def silent(probe: list[str], *args: object, **kwargs: object):
        return _proc(stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", silent)
    assert _tool_version(["python", "-m", "ruff"], tmp_path) is None


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
