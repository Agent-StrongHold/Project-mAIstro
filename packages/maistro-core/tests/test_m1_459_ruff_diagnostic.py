"""Temporary diagnostic for Ruff formatting on the #459 harness."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_emit_ruff_formatter_delta_for_cross_product_harness() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    harness = repo_root / "tests" / "cross_product_parity" / "harness.py"
    result = subprocess.run(
        ["ruff", "format", "--diff", str(harness)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
