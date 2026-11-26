"""#2319 — unwired skills/repertoire packages stay RETIREd, not CONNECT."""

from __future__ import annotations

import json
from pathlib import Path

_DISPOSITIONS = Path(__file__).resolve().parents[3] / "quality" / "reachability-dispositions.json"

_MODULES = {
    "maistro.repertoire",
    "maistro.repertoire.protocol",
    "maistro.repertoire.run",
    "maistro.repertoire.types",
    "maistro.skills.catalog",
    "maistro.skills.connectors",
    "maistro.skills.forge",
    "maistro.skills.loader",
}


def test_supply_chain_unwired_is_retired_with_replaced_by() -> None:
    payload = json.loads(_DISPOSITIONS.read_text(encoding="utf-8"))
    group = next(g for g in payload["groups"] if g["id"] == "supply-chain-unwired")
    assert group["disposition"] == "RETIRE"
    assert set(group["modules"]) == _MODULES
    replaced = str(group["replaced_by"])
    assert "import_pipeline" in replaced or "skills.registry" in replaced
    assert "repertoire" in replaced.lower() or "learnings" in replaced
    assert "2319" in str(group["rationale"])
