"""Temporary formatter diagnostic for PR #726; removed after capturing Ruff's diff."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "test_check_cross_package_imports.py"


def test_report_exact_ruff_formatter_delta():
    proc = subprocess.run(
        ["uv", "run", "ruff", "format", "--diff", str(TARGET)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    pytest.fail(proc.stdout + proc.stderr)
