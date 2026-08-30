"""Regression for multi-concept no-new-islands ownership (#460)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-m1-convergence-freeze.py"
POLICY = ROOT / "quality" / "m1-convergence-freeze.json"
ONTOLOGY = ROOT / "quality" / "shared-interop-ontology-v1.json"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m1_convergence_freeze_multi", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_one_valid_concept_cannot_launder_an_invalid_shared_owner() -> None:
    checker = _module()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    ontology = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    source = '''class RunEventStore:
    """M1 product-local projection: Event"""
'''

    failures = checker.new_shared_owner_violations(
        source,
        "",
        module="maistro.events.projection",
        policy=policy,
        ontology=ontology,
    )

    assert len(failures) == 1
    assert "Run" in failures[0]
    assert "Event" not in failures[0]
