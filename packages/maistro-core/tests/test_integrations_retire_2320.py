"""#2320 — integration bridges stay RETIREd; empty media tool package gone."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DISPOSITIONS = _REPO_ROOT / "quality" / "reachability-dispositions.json"
_BASELINE = _REPO_ROOT / "quality" / "reachability-baseline.json"

_BRIDGE_MODULES = {
    "maistro.integrations",
    "maistro.integrations.coinswarm",
    "maistro.integrations.home_assistant",
    "maistro.integrations.ntfy",
    "maistro.integrations.turing",
}


def test_integrations_bridges_retired_with_replaced_by() -> None:
    payload = json.loads(_DISPOSITIONS.read_text(encoding="utf-8"))
    group = next(g for g in payload["groups"] if g["id"] == "integrations-bridges")
    assert group["disposition"] == "RETIRE"
    assert set(group["modules"]) == _BRIDGE_MODULES
    replaced = str(group["replaced_by"])
    assert "mcp" in replaced.lower() or "Capabilities" in replaced
    assert "2320" in str(group["rationale"])
    assert "root" not in group


def test_tools_unwired_group_and_media_package_gone() -> None:
    payload = json.loads(_DISPOSITIONS.read_text(encoding="utf-8"))
    assert not any(g["id"] == "tools-unwired" for g in payload["groups"])
    baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
    modules = baseline["unreachable"]
    assert "maistro.tools.media" not in modules
    assert importlib.util.find_spec("maistro.tools.media") is None
