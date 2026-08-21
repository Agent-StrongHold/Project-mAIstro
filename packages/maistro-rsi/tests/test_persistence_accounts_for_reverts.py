"""Regression test: a revert commit (from the checkpoint reviewer) is a real,
legitimate commit on baseline_branch that isn't in result.cycles as a
promotion. _check_persistence_integrity must not false-alarm on it, and
export_promotions must not export the reverted promotion or its own revert
commit as if either were harvestable work — both were caught live in the
running 150-cycle shakedown (a resume commit produced the identical false
alarm before this fix)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import structlog.testing

from maistro_evolve.improvement import ImprovementKind
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
        report_dir=str(tmp_path / "reports"),
    )
    loop = LocalRsiLoop(config, apply_patch=None)
    loop._setup_baseline()
    loop._last_reviewed_ref = loop._start_ref
    return loop


def test_revert_does_not_false_alarm_persistence_check(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    (loop._baseline / "risky.py").write_text("x = 1\n", encoding="utf-8")
    _git(loop._baseline, "add", "-A")
    _git(loop._baseline, "commit", "-q", "-m", "cycle 1: risky change")
    sha = _git(loop._baseline, "rev-parse", "HEAD").stdout.strip()

    result = LocalRsiResult(
        cycles=[
            CycleOutcome(
                index=1,
                changed=True,
                tests_passed=True,
                promoted=True,
                target="risky.py",
                composite=0.5,
                sha=sha,
                kind=ImprovementKind.FEATURE,
                regression_judge_score=0.5,
            )
        ]
    )
    report_dir = Path(loop._config.report_dir)
    loop._review_promotions(result, report_dir)  # cold start -> reverts

    with structlog.testing.capture_logs() as logs:
        loop._check_persistence_integrity(result, "test")

    mismatches = [e for e in logs if e.get("event") == "rsi_local_persistence_mismatch"]
    assert not mismatches, (
        "the revert commit is real history but not a 'promotion' — "
        "_check_persistence_integrity must count it via _non_promotion_commits, "
        "not treat it as an unexplained divergence"
    )


def test_export_excludes_reverted_promotion_and_its_own_revert_commit(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    (loop._baseline / "risky.py").write_text("x = 1\n", encoding="utf-8")
    _git(loop._baseline, "add", "-A")
    _git(loop._baseline, "commit", "-q", "-m", "cycle 1: risky change")
    sha = _git(loop._baseline, "rev-parse", "HEAD").stdout.strip()

    result = LocalRsiResult(
        cycles=[
            CycleOutcome(
                index=1,
                changed=True,
                tests_passed=True,
                promoted=True,
                target="risky.py",
                composite=0.5,
                sha=sha,
                kind=ImprovementKind.FEATURE,
                regression_judge_score=0.5,
            )
        ]
    )
    report_dir = Path(loop._config.report_dir)
    loop._review_promotions(result, report_dir)

    export_dir = report_dir / "export"
    loop.export_promotions(export_dir, clear=True)
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    # Neither the original (reverted) promotion nor its own revert commit is
    # harvestable work — a harvester opening a PR for 'Revert "cycle 1..."'
    # would be nonsensical bookkeeping, not a real improvement.
    assert manifest == []
    assert list(export_dir.glob("*.patch")) == []
