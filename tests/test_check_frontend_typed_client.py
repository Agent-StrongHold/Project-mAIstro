"""Tests for the frontend typed-client ratchet (Workspace cutover P0.3, #1048)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-frontend-typed-client.py"
LOGIN = ROOT / "packages/hive-conductor/frontend/src/pages/Login.tsx"
API = ROOT / "packages/hive-conductor/frontend/src/lib/api.ts"
AGENTS = ROOT / "packages/hive-conductor/frontend/src/pages/Agents.tsx"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_frontend_typed_client", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_raw_fetch_outside_lib_is_measured(gate) -> None:
    violations = gate._scan_raw_fetch(LOGIN)
    assert any(item.kind == "raw_fetch" and item.line_no == 83 for item in violations)


def test_raw_fetch_inside_lib_is_ignored(gate) -> None:
    assert gate._scan_raw_fetch(API) == []


def test_hand_typed_in_pages_is_measured(gate) -> None:
    violations = gate._scan_hand_typed(AGENTS)
    assert any(item.kind == "hand_typed" and item.subject == "Agent" for item in violations)


def test_waiver_skips_a_call_site(gate, tmp_path: Path) -> None:
    page = tmp_path / "Waived.tsx"
    page.write_text(
        'fetch("/v1/sidecar"); // frontend-typed-client: allow served by sidecar\n',
        encoding="utf-8",
    )
    lines = page.read_text(encoding="utf-8").splitlines()
    assert gate._is_waived(lines, 0)


def test_new_debt_needs_authorization(gate) -> None:
    key = "raw_fetch::packages/hive-conductor/frontend/src/pages/Dashboard.tsx:51"
    failures = gate.compare({key}, set(), set(), set())
    assert any("NEW frontend typed-client debt" in failure for failure in failures)


def test_fixed_debt_must_leave_the_candidate_ledger(gate) -> None:
    key = "hand_typed::packages/hive-conductor/frontend/src/pages/Agents.tsx:20:Agent"
    assert gate.compare(set(), {key}, {key}, set()) == [
        f"{key}: fixed -- delete it from the candidate ledger"
    ]
