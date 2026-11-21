"""#2316 — tools.approval packages are reachable from the governed tool seam."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DISPOSITIONS = _REPO_ROOT / "quality" / "reachability-dispositions.json"
_BASELINE = _REPO_ROOT / "quality" / "reachability-baseline.json"

_MODULES = (
    "maistro.tools.approval",
    "maistro.tools.approval.gate",
    "maistro.tools.approval.protocols",
    "maistro.tools.approval.types",
)


def test_tools_approval_group_pruned_and_modules_reachable() -> None:
    payload = json.loads(_DISPOSITIONS.read_text(encoding="utf-8"))
    assert not any(g["id"] == "tools-approval-and-reversibility" for g in payload["groups"])
    unreachable = set(json.loads(_BASELINE.read_text(encoding="utf-8"))["unreachable"])
    for module in _MODULES:
        assert module not in unreachable, module
