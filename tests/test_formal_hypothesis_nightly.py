"""Regression test for the formal suite's live nightly Hypothesis profile."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_nightly_flag_selects_live_hypothesis_profile() -> None:
    env = os.environ.copy()
    env["MAISTRO_FORMAL_NIGHTLY_EXAMPLES"] = "321"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "formal/models/test_hypothesis_profile.py",
            "-q",
            "--nightly",
            "--hypothesis-seed=0",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
