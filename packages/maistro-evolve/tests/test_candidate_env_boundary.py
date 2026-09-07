"""Evolve's test-executing gates run behind the credential boundary (#78).

`run_test_selection` (tdd evidence + the mutation probe's executor) and
`measure_coverage_detailed` spawn pytest over the candidate's tree — its
conftest, fixtures and declared plugins execute in that process tree. These
tests pin that those subprocesses receive the boundary environment, never the
harness's ambient one, and that the evolve fallback stays equivalent to the
canonical base when maistro-core is importable.
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


def test_fallback_base_matches_the_canonical_boundary() -> None:
    """The inline fallback (standalone evolve installs) must mirror the
    canonical base exactly — a drift here would make the two runtimes give
    candidates different environments, and the weaker one would win."""
    from maistro.sandbox.credential_boundary import CANDIDATE_BASE_ENV

    import maistro_evolve._candidate_env as ce

    assert ce._FALLBACK_BASE == dict(CANDIDATE_BASE_ENV)
    # With core importable (the integrated RSI runtime), delegation is exact.
    assert ce.candidate_env() == dict(CANDIDATE_BASE_ENV)
