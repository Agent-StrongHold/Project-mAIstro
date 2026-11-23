"""#2315 — remaining unenforced controls stay CONNECT-parked, not fake-wired."""

from __future__ import annotations

import json
from pathlib import Path

_DISPOSITIONS = Path(__file__).resolve().parents[3] / "quality" / "reachability-dispositions.json"

_PARKED = {
    "maistro.security.task_policy",
    "maistro.security.trust_boundary",
    "maistro.security.warden.flag_response",
}

_CONNECTED = {
    "maistro.security.guardrail",
    "maistro.security.strike_recovery",
}


def test_security_unenforced_partial_connect_and_park() -> None:
    payload = json.loads(_DISPOSITIONS.read_text(encoding="utf-8"))
    group = next(g for g in payload["groups"] if g["id"] == "security-unenforced-controls")
    assert group["disposition"] == "CONNECT"
    modules = set(group["modules"])
    assert modules == _PARKED
    assert modules.isdisjoint(_CONNECTED)
    rationale = str(group["rationale"])
    assert "2315" in rationale
    assert "guardrail" in rationale.lower() or "ToolGuardrail" in rationale
    assert "strike" in rationale.lower()
