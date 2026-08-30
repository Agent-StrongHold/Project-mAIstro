"""Temporary CI-only diagnostic for exact Ruff formatter output on #746."""

from __future__ import annotations

import subprocess

import pytest


def test_emit_exact_ruff_format_diff() -> None:
    """Fail with Ruff's exact patch so the adapter can be formatted deterministically."""

    result = subprocess.run(
        [
            "ruff",
            "format",
            "--diff",
            "packages/maistro-canvas/src/maistro_canvas/canvas/canonical_execution.py",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    pytest.fail(f"ruff format diagnostic:\n{result.stdout}\n{result.stderr}")
