"""Tests for the principal-identity ratchet (Workspace cutover P0.1)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-principal-identity.py"
BASELINE = ROOT / "quality" / "principal-identity-baseline.json"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_principal_identity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_baseline_matches_current_violations(gate) -> None:
    violations = gate.collect_violations()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["tolerated"]
    current = {item.key(): item.detail for item in violations}
    assert set(baseline) == set(current)


def test_no_new_violations(gate) -> None:
    new_violations, stale_keys, _ = gate.audit()
    assert not new_violations
    assert not stale_keys
