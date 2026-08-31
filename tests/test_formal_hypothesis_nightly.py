"""Regression test for the formal suite's live Hypothesis modes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_profile(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "formal/models/test_hypothesis_profile.py",
            "-q",
            *args,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_formal_hypothesis_modes_are_live_and_suite_owned() -> None:
    nightly_env = os.environ.copy()
    nightly_env["MAISTRO_FORMAL_NIGHTLY_EXAMPLES"] = "321"
    nightly = _run_profile(
        "--nightly",
        "--hypothesis-seed=12345",
        env=nightly_env,
    )
    assert nightly.returncode == 0, nightly.stdout + nightly.stderr

    replay_env = os.environ.copy()
    replay_env["MAISTRO_FORMAL_CI_EXAMPLES"] = "17"
    replay = _run_profile("--hypothesis-seed=0", env=replay_env)
    assert replay.returncode == 0, replay.stdout + replay.stderr
