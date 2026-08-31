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


def _contract() -> tuple[dict[str, object], dict[str, object]]:
    return (
        json.loads(POLICY.read_text(encoding="utf-8")),
        json.loads(ONTOLOGY.read_text(encoding="utf-8")),
    )


def test_one_valid_concept_cannot_launder_an_invalid_shared_owner() -> None:
    checker = _module()
    policy, ontology = _contract()
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
    assert "overlaps Run." in failures[0]
    assert "overlaps Event" not in failures[0]


def test_retired_events_checkpoint_family_cannot_regain_checkpoint_authority() -> None:
    checker = _module()
    policy, ontology = _contract()

    failures = checker.new_shared_owner_violations(
        "class CheckpointStore:\n    pass\n",
        "",
        module="maistro.events.checkpoints",
        policy=policy,
        ontology=ontology,
    )

    assert len(failures) == 1
    assert "Checkpoint" in failures[0]
