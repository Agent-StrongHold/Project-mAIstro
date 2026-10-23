"""Tests for the principal-identity ratchet (Workspace cutover P0.1)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-principal-identity.py"
ROUTE = "packages/hive-conductor/backend/routes/x.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_principal_identity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dict_shaped_user_access_is_one_entry_per_file(gate) -> None:
    source = (
        "def handler(request):\n"
        "    a = request.state.user['id']\n"
        "    b = getattr(request.state, 'user', None)\n"
        "    setattr(request.state, 'user', {})\n"
    )
    [violation] = gate.scan_source(ROUTE, source)
    assert violation.key() == f"state_user_access::{ROUTE}"
    assert violation.detail.startswith("3 ")


def test_principal_carrier_is_not_a_violation(gate) -> None:
    source = "def handler(request):\n    return request.state.principal.user_id\n"
    assert gate.scan_source(ROUTE, source) == []


def test_parallel_principal_class_is_a_violation_outside_the_owner(gate) -> None:
    source = "class SessionUser:\n    roles: list[str]\n"
    rel = "packages/maistro-canvas/src/maistro_canvas/x.py"
    [violation] = gate.scan_source(rel, source)
    assert violation.key() == f"parallel_principal_class::{rel}::SessionUser"
    assert gate.scan_source("packages/maistro-core/src/maistro/identity/principal.py", source) == []


def test_new_violation_needs_a_grant_landed_at_the_base(gate) -> None:
    current = {"a", "b"}
    assert gate.compare(current, current, {"a"}, set()) == [
        "b: NEW parallel principal surface absent from the trusted base and not previously authorized"
    ]
    assert gate.compare(current, current, {"a"}, {"b"}) == []


def test_candidate_ledger_must_match_the_tree(gate) -> None:
    failures = gate.compare({"a"}, {"a", "fixed"}, {"a", "fixed"}, set())
    assert failures == ["fixed: fixed -- delete it from the candidate ledger"]
