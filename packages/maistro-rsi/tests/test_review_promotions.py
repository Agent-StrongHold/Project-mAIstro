"""Integration test for LocalRsiLoop._review_promotions: real git commits,
real revert, real supersession detection — the mechanics behind the
checkpoint-time RLPHD gate (promotion_review.py)."""

from __future__ import annotations

import subprocess
from pathlib import Path

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


def _commit_file(loop: LocalRsiLoop, filename: str, content: str, message: str) -> str:
    (loop._baseline / filename).write_text(content, encoding="utf-8")
    _git(loop._baseline, "add", "-A")
    _git(loop._baseline, "commit", "-q", "-m", message)
    return _git(loop._baseline, "rev-parse", "HEAD").stdout.strip()


def test_cold_start_low_confidence_promotion_gets_reverted_and_saved(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    sha = _commit_file(loop, "risky.py", "x = 1\n", "cycle 1: risky change")
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
                regression_judge_score=0.5,  # ambiguous — exactly cycle-2's real case
            )
        ]
    )
    report_dir = Path(loop._config.report_dir)
    loop._review_promotions(result, report_dir)

    # Cold start (no prior RLPHD calibration) predicts p=0.5 < theta=0.7 for
    # ANY action class's first encounter -> revert.
    log = _git(loop._baseline, "log", "--oneline").stdout
    assert "Revert" in log
    # The file didn't exist before this commit, so a clean revert removes it.
    assert not (loop._baseline / "risky.py").is_file()

    flagged = list((report_dir / "flagged").glob("*.patch"))
    assert len(flagged) == 1
    meta = list((report_dir / "flagged").glob("*.json"))
    assert len(meta) == 1
    import json

    data = json.loads(meta[0].read_text(encoding="utf-8"))
    assert data["sha"] == sha
    assert data["target"] == "risky.py"


def test_superseded_promotion_is_never_reverted(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    sha1 = _commit_file(loop, "shared.py", "v1\n", "cycle 1")
    _commit_file(loop, "shared.py", "v2\n", "cycle 2: builds on cycle 1")
    result = LocalRsiResult(
        cycles=[
            CycleOutcome(
                index=1,
                changed=True,
                tests_passed=True,
                promoted=True,
                target="shared.py",
                composite=0.5,
                sha=sha1,
                kind=ImprovementKind.FEATURE,
                regression_judge_score=0.3,  # would otherwise clearly revert
            ),
        ]
    )
    report_dir = Path(loop._config.report_dir)
    loop._review_promotions(result, report_dir)

    # cycle 2 (not in `result.cycles`, simulating an untracked later commit
    # that touched the same file) makes reverting cycle 1 unsafe — must skip.
    log = _git(loop._baseline, "log", "--oneline").stdout
    assert "Revert" not in log
    assert (loop._baseline / "shared.py").read_text(encoding="utf-8") == "v2\n"
    assert not (report_dir / "flagged").exists()


def test_last_reviewed_ref_advances_so_reviewed_commits_are_not_rescanned(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    sha = _commit_file(loop, "a.py", "1\n", "cycle 1")
    result = LocalRsiResult(
        cycles=[
            CycleOutcome(
                index=1,
                changed=True,
                tests_passed=True,
                promoted=True,
                target="a.py",
                composite=0.9,
                sha=sha,
                kind=ImprovementKind.DOC,
                regression_judge_score=0.95,
            )
        ]
    )
    report_dir = Path(loop._config.report_dir)
    before = loop._last_reviewed_ref
    loop._review_promotions(result, report_dir)
    assert loop._last_reviewed_ref != before
    assert loop._last_reviewed_ref == _git(loop._baseline, "rev-parse", "HEAD").stdout.strip()


def test_no_promotions_since_last_review_is_a_safe_noop(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    result = LocalRsiResult(cycles=[])
    report_dir = Path(loop._config.report_dir)
    before = loop._last_reviewed_ref
    loop._review_promotions(result, report_dir)  # must not raise
    assert loop._last_reviewed_ref == before
