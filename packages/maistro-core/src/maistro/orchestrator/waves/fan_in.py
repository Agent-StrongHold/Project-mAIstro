"""Git-based wave fan-in merge (SPEC-255 / ADR-052)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from maistro.orchestrator.waves.types import ConflictRecord, FanInResult, WaveHandle
from maistro.tools.git.shadow import _GIT_ENV, ShadowGitWorkspace


def _git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **_GIT_ENV}
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=check, capture_output=True, text=True
    )


def _rev_parse(workspace_ref: Path, ref: str) -> str:
    return _git(["rev-parse", ref], cwd=workspace_ref).stdout.strip()


def fan_in(
    workspace: ShadowGitWorkspace,
    *,
    base_branch: str,
    fan_in_branch: str,
    waves: tuple[WaveHandle, ...],
) -> FanInResult:
    succeeded = tuple(w for w in waves if w.status == "succeeded")
    failed_waves = tuple(w for w in waves if w.status != "succeeded")

    workspace_ref = workspace.workspace_ref
    _git(["checkout", "-b", fan_in_branch, base_branch], cwd=workspace_ref)

    conflicts: list[ConflictRecord] = []
    prior_wave_id = base_branch

    for wave in succeeded:
        sha_a = _rev_parse(workspace_ref, "HEAD")
        result = _git(["merge", "--no-edit", wave.branch], cwd=workspace_ref, check=False)
        if result.returncode == 0:
            prior_wave_id = wave.wave_id
            continue

        sha_b = _rev_parse(workspace_ref, wave.branch)
        conflicting_paths = _git(
            ["diff", "--name-only", "--diff-filter=U"], cwd=workspace_ref
        ).stdout.splitlines()
        for path in conflicting_paths:
            if not path:
                continue
            conflicts.append(
                ConflictRecord(
                    path=path,
                    wave_a=prior_wave_id,
                    wave_b=wave.wave_id,
                    sha_a=sha_a,
                    sha_b=sha_b,
                )
            )
        _git(["merge", "--abort"], cwd=workspace_ref)

    merged_sha = _rev_parse(workspace_ref, "HEAD")

    return FanInResult(
        merged_sha=merged_sha,
        conflicts=tuple(conflicts),
        failed_waves=failed_waves,
    )
