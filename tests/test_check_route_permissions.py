"""Tests for the authenticated route-permission ratchet (Workspace cutover P0.2).

The repo-level run lives in quality.yml beside check_enumerations.py, because
both import the hive app; these tests pin the registry contract without it.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-route-permissions.py"
TODAY = date(2026, 10, 1)
_BASE = {"owner": "@someone", "disposition": "permanent", "reason": "because"}


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_route_permissions", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_prefix_is_the_first_v1_segment(gate) -> None:
    assert gate._v1_prefix("/v1/dags/{id}/run") == "/v1/dags"
    assert gate._v1_prefix("/health") is None


def test_entry_must_choose_permission_or_exemption(gate) -> None:
    assert gate.entry_problems("/v1/x", dict(_BASE), TODAY)
    both = {**_BASE, "permission": "x.write", "exempt_reason": "why"}
    assert gate.entry_problems("/v1/x", both, TODAY)
    assert not gate.entry_problems("/v1/x", {**_BASE, "permission": "x.write"}, TODAY)
    assert not gate.entry_problems("/v1/x", {**_BASE, "exempt_reason": "why"}, TODAY)


def test_temporary_exemption_needs_an_unexpired_date(gate) -> None:
    entry = {**_BASE, "exempt_reason": "why", "disposition": "temporary", "issue": 53}
    assert gate.entry_problems("/v1/x", entry, TODAY)
    assert gate.entry_problems("/v1/x", {**entry, "expires": "2026-09-30"}, TODAY)
    assert not gate.entry_problems("/v1/x", {**entry, "expires": "2026-12-31"}, TODAY)


def test_stale_or_public_registry_entries_fail_hard(gate) -> None:
    registry = {"/v1/gone": {**_BASE, "permission": "x"}, "/v1/open": {**_BASE, "permission": "x"}}
    problems = gate.registry_problems({"/v1/open"}, registry, {"/v1/open"}, TODAY)
    assert len(problems) == 2


def test_new_exemption_needs_a_grant_landed_at_the_base(gate) -> None:
    candidate = {"/v1/x": {**_BASE, "exempt_reason": "why"}}
    exemptions = gate.new_exemptions(candidate, {})
    assert exemptions == {"exempt::/v1/x"}
    assert gate.compare(set(), set(), set(), exemptions, set()) == [
        "exempt::/v1/x: NEW exemption needs an already-landed authorization"
    ]
    assert gate.new_exemptions(candidate, candidate) == set()


def test_declaring_a_prefix_requires_deleting_its_gap(gate) -> None:
    assert gate.compare(set(), {"/v1/x"}, {"/v1/x"}, set(), set()) == [
        "/v1/x: declared now -- delete it from the candidate ledger"
    ]
