"""Architecture fitness: one HTTP principal type (Workspace cutover P0.1 / #53)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _REPO_ROOT / "scripts" / "check-principal-identity.py"


def test_principal_identity_ledger_matches_the_tree(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("check_principal_identity", _SCRIPT)
    assert spec and spec.loader
    gate = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, gate)
    spec.loader.exec_module(gate)
    violations, _ = gate.collect_violations()
    ledger = json.loads(gate.BASELINE.read_text(encoding="utf-8"))["tolerated"]
    current = {item.key() for item in violations}
    assert not current - set(ledger), "new: " + "\n".join(sorted(current - set(ledger)))
    assert not set(ledger) - current, "fixed: " + "\n".join(sorted(set(ledger) - current))
