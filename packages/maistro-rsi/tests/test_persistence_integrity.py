"""``_check_persistence_integrity``: the runtime self-check that surfaces a
resume/commit divergence loudly instead of requiring a manual git-log audit —
the exact class of bug that let 32 promoted patches silently vanish across a
restart before anyone noticed."""

from __future__ import annotations

import subprocess
from pathlib import Path

import structlog.testing

from maistro_rsi.local_loop import CycleOutcome, LocalRsiConfig, LocalRsiLoop, LocalRsiResult, _git


def _git_run(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git_run(path, "init", "-q")
    _git_run(path, "config", "user.email", "rsi@test.local")
    _git_run(path, "config", "user.name", "RSI Test")
    (path / "value.txt").write_text("0\n", encoding="utf-8")
    _git_run(path, "add", "-A")
    _git_run(path, "commit", "-q", "-m", "init")
    return path


def _loop(tmp_path: Path) -> LocalRsiLoop:
    repo = _make_repo(tmp_path / "src")
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=1,
    )
    loop = LocalRsiLoop(config, apply_patch=None)
    loop._setup_baseline()
    return loop


def test_mismatch_logs_error(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    # Commit one real change directly on baseline_branch (simulating a promoted
    # cycle that landed in git history) but tell the checker the in-memory
    # record believes ZERO promotions happened — a stand-in for exactly what
    # the resume-commit bug produced: git history and the promotion counter
    # silently diverging.
    (loop._baseline / "extra.txt").write_text("x\n", encoding="utf-8")
    _git(loop._baseline, "add", "-A")
    _git(loop._baseline, "commit", "-q", "-m", "untracked by the in-memory count")

    result = LocalRsiResult(cycles=[], baseline_dir=str(loop._baseline))
    with structlog.testing.capture_logs() as logs:
        loop._check_persistence_integrity(result, "test")

    mismatches = [e for e in logs if e.get("event") == "rsi_local_persistence_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0]["recorded_promotions"] == 0
    assert mismatches[0]["actual_commits"] == 1


def test_matching_counts_log_nothing(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    (loop._baseline / "extra.txt").write_text("x\n", encoding="utf-8")
    _git(loop._baseline, "add", "-A")
    _git(loop._baseline, "commit", "-q", "-m", "one promotion")

    result = LocalRsiResult(
        cycles=[CycleOutcome(index=1, changed=True, tests_passed=True, promoted=True)],
        baseline_dir=str(loop._baseline),
    )
    with structlog.testing.capture_logs() as logs:
        loop._check_persistence_integrity(result, "test")

    assert not [e for e in logs if e.get("event") == "rsi_local_persistence_mismatch"]


def test_no_start_ref_is_a_safe_noop(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop._start_ref = None
    result = LocalRsiResult(cycles=[], baseline_dir=str(loop._baseline))
    with structlog.testing.capture_logs() as logs:
        loop._check_persistence_integrity(result, "test")  # must not raise
    assert not [e for e in logs if e.get("event") == "rsi_local_persistence_mismatch"]
