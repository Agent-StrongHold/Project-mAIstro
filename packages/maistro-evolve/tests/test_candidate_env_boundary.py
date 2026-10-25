"""Evolve's test-executing gates run behind the credential boundary (#78).

`run_test_selection` (tdd evidence + the mutation probe's executor) and
`measure_coverage_detailed` spawn pytest over the candidate's tree — its
conftest, fixtures and declared plugins execute in that process tree. These
tests pin that those subprocesses receive the boundary environment, never the
harness's ambient one, and that the ``maistro_evolve._candidate_env`` seam
stays exactly equivalent to the canonical boundary in maistro-core (the seam
cannot import the canonical module — the promotion-surface gate forbids the
import edge — so equivalence is pinned by importing both here, in test code,
which is not on the promotion path).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest


class _Completed:
    returncode = 0
    stdout = ""
    stderr = ""


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture subprocess.run kwargs with a live harness secret in the env."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-harness-secret")

    def _fake_run(command: Any, **kwargs: Any) -> _Completed:
        calls.append({"command": command, **kwargs})
        return _Completed()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    return calls


def test_run_test_selection_uses_the_boundary_env(recorded: list[dict[str, Any]]) -> None:
    from maistro_evolve.tdd_gate import run_test_selection

    rc, _ = run_test_selection(Path("."), ["tests/test_x.py"])
    assert rc == 0
    env = recorded[0]["env"]
    assert "LITELLM_MASTER_KEY" not in env
    # The original reason the old code set this var still holds — red->green
    # reverts a source file between two runs and must not reuse stale bytecode.
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"


def test_measure_coverage_runs_pytest_behind_the_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import maistro_evolve.coverage_gate as cg

    calls: list[dict[str, Any]] = []
    report = json.dumps({"totals": {"percent_covered": 50.0}, "files": {}})
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-harness-secret")

    def _fake_run(command: Any, **kwargs: Any) -> _Completed:
        calls.append({"command": command, **kwargs})
        result = _Completed()
        if "json" in command:
            result.stdout = report
        return result

    monkeypatch.setattr(cg.subprocess, "run", _fake_run)
    total, missing = cg.measure_coverage_detailed(".")
    assert (total, missing) == (50.0, {})
    assert len(calls) == 2  # the pytest run and the json report parse
    for call in calls:
        # Both run behind the boundary — the report parser reads
        # candidate-produced bytes, so it gets no exemption either.
        assert call["env"] is not None
        assert "LITELLM_MASTER_KEY" not in call["env"]
        assert call["env"]["PATH"] == "/usr/local/bin:/usr/bin:/bin"


def test_candidate_env_equivalence() -> None:
    """The seam must mirror the canonical boundary exactly — a drift here
    would make the two runtimes give candidates different environments, and
    the weaker one would win. The seam cannot import the canonical module
    (the promotion-surface gate forbids the edge: maistro/sandbox/__init__
    re-exports the whole subsystem), so both are imported here, in test
    code, and compared behaviorally — base, grants, and the shadow refusal."""
    import maistro_evolve._candidate_env as ce
    from maistro.sandbox.credential_boundary import (
        CANDIDATE_BASE_ENV as CORE_BASE,
    )
    from maistro.sandbox.credential_boundary import (
        candidate_env as core_candidate_env,
    )

    assert dict(ce.CANDIDATE_BASE_ENV) == dict(CORE_BASE)
    assert ce.candidate_env() == core_candidate_env()
    # The grants channel behaves identically, including the refusal.
    assert ce.candidate_env({"PROVIDER_KEY": "granted"}) == core_candidate_env(
        {"PROVIDER_KEY": "granted"}
    )
    with pytest.raises(ValueError, match="shadows the sandbox base environment"):
        ce.candidate_env({"PATH": "/hax"})
    with pytest.raises(ValueError, match="shadows the sandbox base environment"):
        core_candidate_env({"PATH": "/hax"})


def test_the_seam_reads_nothing_ambient_on_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam itself is the implementation now (no delegation to core), so
    its no-ambient-inheritance property is asserted directly: with harness
    secrets in the environment, the candidate env contains exactly the base.
    A fallback that inverted into ambient inheritance would be the exact bug
    #78 closes."""
    import maistro_evolve._candidate_env as ce

    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-harness-secret")
    env = ce.candidate_env()
    assert env == dict(ce.CANDIDATE_BASE_ENV)
    assert "LITELLM_MASTER_KEY" not in env


def test_windows_forwards_system_basics_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Windows branch mirrors the canonical one: system basics by NAME
    only (python.exe cannot start without SYSTEMROOT), never a spread."""
    import os

    import maistro_evolve._candidate_env as ce

    monkeypatch.setattr(os, "name", "nt", raising=False)
    monkeypatch.setenv("SYSTEMROOT", "C:\\Windows")
    monkeypatch.setenv("SECRET_HARNESS_KEY", "sk-should-not-forward")
    env = ce.candidate_env()
    assert env["SYSTEMROOT"] == "C:\\Windows"
    assert "SECRET_HARNESS_KEY" not in env
