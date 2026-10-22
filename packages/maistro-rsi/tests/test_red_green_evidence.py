"""Integration test for the red→green orchestration (real git + pytest).

Since #392 the probe is ``fail_first.collect_fail_first_evidence``: the same
revert→run→restore mechanism the old ``_red_green_evidence`` performed, now
additionally recording the base/candidate SHAs, failing test identities, the
failure-output digest, and a reproducibility re-run. This file keeps asserting
the red→green *behavior* (the TddEvidence signal view); the full evidence
contract lives in ``test_fail_first.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from maistro_rsi.fail_first import collect_fail_first_evidence


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.mark.skipif(
    subprocess.run([sys.executable, "-m", "pytest", "--version"], capture_output=True).returncode
    != 0,
    reason="pytest not runnable as a subprocess",
)
def test_red_on_baseline_green_on_candidate(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.co")
    _git(repo, "config", "user.name", "t")
    # baseline: f() returns 1, no test
    (repo / "src.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    _git(repo, "branch", "base")
    # candidate: f() returns 2 (source change) + a test that demands 2
    (repo / "src.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    (repo / "test_src.py").write_text(
        "from src import f\n\ndef test_f():\n    assert f() == 2\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "candidate")

    ev = collect_fail_first_evidence(repo, "base", ["src.py"], ["test_src.py"], timeout=120)

    assert ev is not None
    tdd = ev.tdd_view(["test_src.py"])
    assert tdd.candidate_changed_rc == 0  # green on candidate
    assert tdd.baseline_changed_rc not in (None, 0)  # red on baseline
    # And the candidate source was restored after the probe.
    assert "return 2" in (repo / "src.py").read_text(encoding="utf-8")
