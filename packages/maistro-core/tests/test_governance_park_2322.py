"""#2322 — governance.conformance stays CONNECT, post-v1 park explicit."""

from __future__ import annotations

import json
from pathlib import Path

_DISPOSITIONS = Path(__file__).resolve().parents[3] / "quality" / "reachability-dispositions.json"

_MODULES = {
    "maistro.governance.conformance",
    "maistro.governance.conformance_types",
}


def test_governance_conformance_remains_connect_parked() -> None:
    payload = json.loads(_DISPOSITIONS.read_text(encoding="utf-8"))
    group = next(g for g in payload["groups"] if g["id"] == "governance-conformance")
    assert group["disposition"] == "CONNECT"
    assert set(group["modules"]) == _MODULES
    rationale = str(group["rationale"])
    assert "2322" in rationale
    assert "post-v1" in rationale.lower() or "v1.0" in rationale
    assert "60" in str(group.get("root", "")) or "60" in rationale
