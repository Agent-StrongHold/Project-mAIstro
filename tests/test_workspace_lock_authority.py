"""Workspace members share the patched root dependency resolution."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_members_do_not_keep_independent_lockfiles():
    """An ignored member lock can retain vulnerable, invalid standalone metadata."""
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    workspace = manifest["tool"]["uv"]["workspace"]
    excluded = {path for pattern in workspace.get("exclude", []) for path in ROOT.glob(pattern)}
    members = {path for pattern in workspace["members"] for path in ROOT.glob(pattern)}
    stale = sorted(
        str((member / "uv.lock").relative_to(ROOT))
        for member in members - excluded
        if (member / "pyproject.toml").is_file() and (member / "uv.lock").exists()
    )
    assert not stale, f"Workspace members must use root uv.lock; remove stale locks: {stale}"
