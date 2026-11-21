"""#2323 — keep ``maistro.collaboration`` CONNECT / unwired until A2UI."""

from __future__ import annotations

import json
from pathlib import Path

_DISPOSITIONS = Path(__file__).resolve().parents[3] / "quality" / "reachability-dispositions.json"

_MODULES = {
    "maistro.collaboration",
    "maistro.collaboration.session_collab",
    "maistro.collaboration.types",
}


def test_collaboration_remains_connect_parked_until_a2ui() -> None:
    payload = json.loads(_DISPOSITIONS.read_text(encoding="utf-8"))
    group = next(g for g in payload["groups"] if g["id"] == "collaboration")
    assert group["disposition"] == "CONNECT"
    assert set(group["modules"]) == _MODULES
    rationale = str(group["rationale"])
    root = str(group.get("root", ""))
    assert "2323" in rationale
    assert "A2UI" in rationale or "A2UI" in root
    assert "070426-3a1f" in rationale or "070426-3a1f" in root
    assert "v1.0" in rationale.lower() or "workspaces" in rationale.lower()
