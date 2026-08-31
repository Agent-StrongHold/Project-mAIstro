"""Temporary diagnostic: print the pinned Ruff formatting diff for #129 cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


_FILES = (
    "packages/hive-conductor/backend/main.py",
    "packages/hive-conductor/backend/services/dag_run_store.py",
    "packages/hive-conductor/backend/services/engine.py",
    "packages/hive-conductor/backend/tests/test_pm_poc_execution_retirement.py",
    "packages/maistro-core/tests/agents/test_hyperagent.py",
    "packages/maistro-core/tests/agents/test_pm_fleet_retirement.py",
    "packages/maistro-core/tests/agents/test_program_hyperagent.py",
    "packages/maistro-server/src/maistro_server/main.py",
    "packages/maistro-server/tests/test_pm_poc_catalog_retirement.py",
)


def test_print_pinned_ruff_format_diff() -> None:
    root = Path(__file__).resolve().parents[3]
    proc = subprocess.run(
        ["ruff", "format", "--diff", *_FILES],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    pytest.fail(f"ruff returncode={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
