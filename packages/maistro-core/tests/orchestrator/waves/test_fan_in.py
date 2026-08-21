"""Tests for wave fan-out cap enforcement and git fan-in merge (SPEC-255 / ADR-052)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maistro.orchestrator.waves.fan_in import fan_in
from maistro.orchestrator.waves.fan_out import MAX_PARALLEL_CEILING, validate_fan_out_width
from maistro.orchestrator.waves.types import WaveHandle, WaveSpec
from maistro.tools.git.shadow import _GIT_ENV, create_shadow_workspace


def _wave_spec(wave_id: str) -> WaveSpec:
    return WaveSpec(wave_id=wave_id, agent_recipe="r1", inputs={})


class TestValidateFanOutWidth:
    def test_accepts_width_at_or_below_max_parallel(self) -> None:
        validate_fan_out_width((_wave_spec("w1"), _wave_spec("w2")), max_parallel=4)

    def test_accepts_width_at_ceiling(self) -> None:
        specs = tuple(_wave_spec(f"w{i}") for i in range(MAX_PARALLEL_CEILING))
        validate_fan_out_width(specs, max_parallel=MAX_PARALLEL_CEILING)

    def test_raises_when_max_parallel_exceeds_ceiling(self) -> None:
        with pytest.raises(ValueError, match="MAX_PARALLEL_CEILING"):
            validate_fan_out_width((), max_parallel=MAX_PARALLEL_CEILING + 1)

    def test_raises_when_wave_count_exceeds_max_parallel(self) -> None:
        specs = (_wave_spec("w1"), _wave_spec("w2"), _wave_spec("w3"))
        with pytest.raises(ValueError, match="wave_specs"):
            validate_fan_out_width(specs, max_parallel=2)


def _git(args: list[str], cwd: Path) -> None:
    import os

    env = {**os.environ, **_GIT_ENV}
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)


def _rev_parse(cwd: Path, ref: str) -> str:
    import os

    env = {**os.environ, **_GIT_ENV}
    result = subprocess.run(
        ["git", "rev-parse", ref], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _make_wave_branch(
    workspace_ref: Path, base_branch: str, wave_id: str, files: dict[str, str]
) -> str:
    _git(["checkout", "-b", wave_id, base_branch], cwd=workspace_ref)
    for rel_path, content in files.items():
        (workspace_ref / rel_path).write_text(content)
        _git(["add", rel_path], cwd=workspace_ref)
    _git(["commit", "-m", f"wave {wave_id}"], cwd=workspace_ref)
    sha = _rev_parse(workspace_ref, "HEAD")
    _git(["checkout", base_branch], cwd=workspace_ref)
    return sha


class TestFanIn:
    def test_disjoint_waves_merge_cleanly(self, tmp_path: Path) -> None:
        workspace = create_shadow_workspace(tmp_path, "task1")
        workspace_ref = workspace.workspace_ref
        _git(["branch", "main"], cwd=workspace_ref)

        sha1 = _make_wave_branch(workspace_ref, "main", "w1", {"a.txt": "a"})
        sha2 = _make_wave_branch(workspace_ref, "main", "w2", {"b.txt": "b"})

        waves = (
            WaveHandle(wave_id="w1", branch="w1", status="succeeded", head_sha=sha1),
            WaveHandle(wave_id="w2", branch="w2", status="succeeded", head_sha=sha2),
        )
        result = fan_in(workspace, base_branch="main", fan_in_branch="fan-in", waves=waves)

        assert result.merged_sha is not None
        assert result.conflicts == ()
        assert (workspace_ref / "a.txt").exists()
        assert (workspace_ref / "b.txt").exists()

    def test_conflicting_waves_produce_conflict_record(self, tmp_path: Path) -> None:
        workspace = create_shadow_workspace(tmp_path, "task2")
        workspace_ref = workspace.workspace_ref
        _git(["branch", "main"], cwd=workspace_ref)

        sha1 = _make_wave_branch(workspace_ref, "main", "w1", {"shared.txt": "from-w1"})
        sha2 = _make_wave_branch(workspace_ref, "main", "w2", {"shared.txt": "from-w2"})

        waves = (
            WaveHandle(wave_id="w1", branch="w1", status="succeeded", head_sha=sha1),
            WaveHandle(wave_id="w2", branch="w2", status="succeeded", head_sha=sha2),
        )
        result = fan_in(workspace, base_branch="main", fan_in_branch="fan-in2", waves=waves)

        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert conflict.path == "shared.txt"
        assert conflict.wave_a == "w1"
        assert conflict.wave_b == "w2"
        assert (workspace_ref / "shared.txt").read_text() == "from-w1"

    def test_failed_wave_excluded_and_listed(self, tmp_path: Path) -> None:
        workspace = create_shadow_workspace(tmp_path, "task3")
        workspace_ref = workspace.workspace_ref
        _git(["branch", "main"], cwd=workspace_ref)

        sha1 = _make_wave_branch(workspace_ref, "main", "w1", {"a.txt": "a"})

        waves = (
            WaveHandle(wave_id="w1", branch="w1", status="succeeded", head_sha=sha1),
            WaveHandle(wave_id="w2", branch="nonexistent", status="failed", head_sha=None),
        )
        result = fan_in(workspace, base_branch="main", fan_in_branch="fan-in3", waves=waves)

        assert (workspace_ref / "a.txt").exists()
        assert len(result.failed_waves) == 1
        assert result.failed_waves[0].wave_id == "w2"

    def test_zero_succeeded_waves_returns_base_sha(self, tmp_path: Path) -> None:
        workspace = create_shadow_workspace(tmp_path, "task4")
        workspace_ref = workspace.workspace_ref
        _git(["branch", "main"], cwd=workspace_ref)
        base_sha = _rev_parse(workspace_ref, "main")

        waves = (WaveHandle(wave_id="w1", branch="nope", status="running", head_sha=None),)
        result = fan_in(workspace, base_branch="main", fan_in_branch="fan-in4", waves=waves)

        assert result.merged_sha == base_sha
        assert result.failed_waves == waves
