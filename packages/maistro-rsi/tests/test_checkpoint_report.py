"""Tests for long-run checkpointing: periodic progress reports + a rolling,
harvestable export, while the baseline keeps ratcheting forward.

The pure `build_checkpoint_report` is tested directly (no git); the loop-level
checkpoint behaviour reuses the same stub-apply harness as `test_local_loop`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from maistro_rsi.local_loop import (
    CycleOutcome,
    LocalRsiConfig,
    LocalRsiLoop,
    build_checkpoint_report,
)
from maistro_rsi.protocols import MicroVmSandbox


def _git(cwd: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} rc={proc.returncode}: {proc.stderr.strip()}")


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "rsi@test.local")
    _git(path, "config", "user.name", "RSI Test")
    (path / "value.txt").write_text("0\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _make_apply(writer) -> object:
    async def apply(sandbox: MicroVmSandbox, workspace: str, model: str | None = None) -> None:
        writer(Path(workspace))

    return apply


# --------------------------------------------------------------------------- #
# pure report builder
# --------------------------------------------------------------------------- #


def _outcome(index: int, *, target: str, promoted: bool, composite: float = 0.0) -> CycleOutcome:
    return CycleOutcome(
        index=index,
        changed=promoted,
        tests_passed=promoted,
        promoted=promoted,
        files_touched=1 if promoted else 0,
        target=target,
        composite=composite,
    )


def test_report_cumulative_stats() -> None:
    cycles = [
        _outcome(1, target="a.py", promoted=True, composite=0.8),
        _outcome(2, target="b.py", promoted=False),
        _outcome(3, target="a.py", promoted=True, composite=0.6),
    ]
    md, data = build_checkpoint_report(
        cycles, total_planned=10, baseline_dir="/w/baseline", window=5
    )

    assert data["cycles_run"] == 3
    assert data["cycles_planned"] == 10
    assert data["promotions"] == 2
    assert data["promotion_rate"] == round(2 / 3, 3)
    # Composite averages only over promoted cycles.
    assert data["avg_composite"] == round((0.8 + 0.6) / 2, 3)
    # Per-file counts group promotions by target.
    assert data["files_improved"] == {"a.py": 2}
    assert "# RSI checkpoint" in md
    assert "a.py" in md


def test_report_window_only_shows_recent() -> None:
    cycles = [_outcome(i, target=f"f{i}.py", promoted=True, composite=0.5) for i in range(1, 7)]
    _md, data = build_checkpoint_report(cycles, total_planned=6, baseline_dir="/w", window=2)
    # Cumulative counts all 6; the detail window shows only the last 2.
    assert data["promotions"] == 6
    assert [c["index"] for c in data["recent"]] == [5, 6]


def test_report_avg_composite_includes_zero() -> None:
    # 0.0 is a valid promoted composite (non-fitness runs, or an accepted
    # scorecard composing to 0.0) — it must count in the average, not be dropped.
    cycles = [
        _outcome(1, target="a.py", promoted=True, composite=1.0),
        _outcome(2, target="b.py", promoted=True, composite=0.0),
    ]
    _md, data = build_checkpoint_report(cycles, total_planned=2, baseline_dir="/w", window=5)
    assert data["promotions"] == 2
    assert data["avg_composite"] == 0.5  # (1.0 + 0.0) / 2, not 1.0


def test_report_empty_is_safe() -> None:
    md, data = build_checkpoint_report([], total_planned=10, baseline_dir="/w", window=5)
    assert data["cycles_run"] == 0
    assert data["promotion_rate"] == 0.0
    assert data["avg_composite"] == 0.0
    assert data["recent"] == []
    assert "# RSI checkpoint" in md


def test_evolution_section_absent_without_population_summary() -> None:
    md, data = build_checkpoint_report(
        [_outcome(1, target="a.py", promoted=True)], total_planned=1, baseline_dir="/w", window=5
    )
    assert "## Evolution" not in md
    assert "evolution" not in data


@pytest.mark.ac("SPEC-070126-9d37/AC-17")
def test_evolution_section_reports_learning_not_just_work() -> None:
    summary = {
        "population_size": 5,
        "generations": {0: 2, 1: 3},
        "top_genomes": [
            {
                "name": "champion",
                "generation": 1,
                "fitness": 0.82,
                "code_rsi": 0.9,
                "model": "devstral-medium",
                "tdd_rigor": 1.0,
                "test_style": "strict_tdd",
            }
        ],
        "reliability": {"devstral-medium": 0.973, "gemini-2.5-flash": 0.343},
        "benched_models": ["gemini-2.5-flash"],
        "memory": {"learned_successes": "test-first fixes with assertions raise acceptance"},
    }
    md, data = build_checkpoint_report(
        [_outcome(1, target="a.py", promoted=True)],
        total_planned=1,
        baseline_dir="/w",
        window=5,
        population_summary=summary,
    )
    assert data["evolution"] == summary
    assert "## Evolution" in md
    assert "champion" in md and "devstral-medium" in md and "strict_tdd" in md
    assert "gemini-2.5-flash" in md  # both in reliability AND benched
    assert "test-first fixes with assertions" in md


# --------------------------------------------------------------------------- #
# loop-level checkpointing
# --------------------------------------------------------------------------- #


def _bump(ws: Path) -> None:
    f = ws / "value.txt"
    f.write_text(f.read_text() + "x\n", encoding="utf-8")


def test_interim_and_final_checkpoints_written(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")
    reports = tmp_path / "reports"
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=5,
        report_every=2,
        report_dir=str(reports),
    )
    result = LocalRsiLoop(config, apply_patch=_make_apply(_bump)).run()
    assert result.promotions == 5

    # Interim reports at cycles 2 and 4, plus a final report. Cycle 5 coincides
    # with the last cycle, so it is folded into "final" rather than duplicated.
    assert (reports / "checkpoint-cycle-2.md").is_file()
    assert (reports / "checkpoint-cycle-4.md").is_file()
    assert (reports / "checkpoint-final.md").is_file()
    assert not (reports / "checkpoint-cycle-5.md").exists()

    final = json.loads((reports / "checkpoint-final.json").read_text(encoding="utf-8"))
    assert final["cycles_run"] == 5
    assert final["promotions"] == 5


def test_rolling_export_is_complete_and_not_stale(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")
    reports = tmp_path / "reports"
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=4,
        report_every=2,
        report_dir=str(reports),
        # This test is about rolling-export completeness, not the checkpoint
        # reviewer — the fixture rewrites the SAME file every cycle, so a
        # cold-start RLPHD revert (see test_review_promotions.py) would
        # legitimately shrink the exported set, which isn't what's under test
        # here.
        promotion_review=False,
    )
    LocalRsiLoop(config, apply_patch=_make_apply(_bump)).run()

    export = reports / "export"
    manifest = json.loads((export / "manifest.json").read_text(encoding="utf-8"))
    patches = sorted(export.glob("*.patch"))
    # Every promotion (4) is present exactly once — the rolling re-export clears
    # the prior window's patches rather than accumulating duplicates.
    assert len(manifest) == 4
    assert len(patches) == 4


@pytest.mark.ac("SPEC-070126-9d37/AC-17")
def test_live_mode_checkpoint_includes_evolution_section(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")
    reports = tmp_path / "reports"
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=2,
        report_every=0,
        report_dir=str(reports),
        model="testmodel",
        genome_db=str(tmp_path / "pop.db"),
        roster_size=2,
    )
    LocalRsiLoop(config, apply_patch=_make_apply(_bump)).run()

    final_md = (reports / "checkpoint-final.md").read_text(encoding="utf-8")
    final_json = json.loads((reports / "checkpoint-final.json").read_text(encoding="utf-8"))
    assert "## Evolution" in final_md
    assert final_json["evolution"]["population_size"] >= 1


def test_no_report_dir_writes_nothing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=2,
        report_every=1,  # ignored without a report_dir
    )
    # Must not raise and must not create any stray reports directory.
    LocalRsiLoop(config, apply_patch=_make_apply(_bump)).run()
    assert not (tmp_path / "reports").exists()
