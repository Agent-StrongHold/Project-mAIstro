"""Temporary formatter diagnostic for PR #724; remove after capturing Ruff's diff."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TARGET = "packages/maistro-core/tests/fitness/test_import_boundaries.py"


def test_print_exact_ruff_format_diff() -> None:
    ruff = shutil.which("ruff")
    assert ruff is not None, "CI environment must provide Ruff"
    proc = subprocess.run(
        [ruff, "format", "--diff", TARGET],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    pytest.fail(proc.stdout + proc.stderr)
