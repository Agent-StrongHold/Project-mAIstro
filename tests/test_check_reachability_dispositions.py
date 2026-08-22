"""Tests for the unreachable-module disposition ledger gate (#33).

The ledger's value is that it cannot drift from the baseline it explains, so the
properties worth pinning are the failures: an unexplained module, a disposition
left behind after its module became reachable, and a row that names a decision
without the evidence that makes it checkable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-reachability-dispositions.py"

SUBSYSTEMS = {"Memory", "Builders pipeline"}


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_reachability_dispositions", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ledger(*groups: dict) -> dict:
    return {"groups": list(groups)}


def group(**overrides) -> dict:
    base = {
        "id": "memory-bits",
        "subsystem": "Memory",
        "disposition": "CONNECT",
        "rationale": "why",
        "root": "maistro.container",
        "modules": ["a.b"],
    }
    base.update(overrides)
    return base


def test_a_matching_ledger_passes(gate) -> None:
    assert gate.audit(ledger(group()), {"a.b"}, SUBSYSTEMS) == []


def test_an_unexplained_unreachable_module_fails(gate) -> None:
    failures = gate.audit(ledger(group()), {"a.b", "c.d"}, SUBSYSTEMS)
    assert any("c.d" in f and "no disposition" in f for f in failures)


def test_a_disposition_for_a_now_reachable_module_fails(gate) -> None:
    """The stale half of the ratchet. A row left behind after its module was
    wired would silently absorb a later regression on that name."""
    failures = gate.audit(ledger(group(modules=["a.b", "gone.away"])), {"a.b"}, SUBSYSTEMS)
    assert any("gone.away" in f and "not in the reachability baseline" in f for f in failures)


def test_connect_without_a_root_fails(gate) -> None:
    """'Someone should wire this' is not a disposition."""
    failures = gate.audit(ledger(group(root="")), {"a.b"}, SUBSYSTEMS)
    assert failures == ["memory-bits: CONNECT requires a non-empty 'root'"]


def test_retire_without_a_replacement_fails(gate) -> None:
    failures = gate.audit(ledger(group(disposition="RETIRE", root=None)), {"a.b"}, SUBSYSTEMS)
    assert any("RETIRE requires a non-empty 'replaced_by'" in f for f in failures)


def test_library_needs_only_a_rationale(gate) -> None:
    assert gate.audit(ledger(group(disposition="LIBRARY", root=None)), {"a.b"}, SUBSYSTEMS) == []


def test_a_missing_rationale_fails_for_every_disposition(gate) -> None:
    failures = gate.audit(ledger(group(disposition="LIBRARY", rationale=" ")), {"a.b"}, SUBSYSTEMS)
    assert "memory-bits: needs a rationale" in failures


def test_a_subsystem_outside_the_matrix_fails(gate) -> None:
    """The two M0 artifacts must agree on what a subsystem is."""
    failures = gate.audit(ledger(group(subsystem="Invented")), {"a.b"}, SUBSYSTEMS)
    assert any("'Invented' is not a row in CONVERGENCE-MATRIX.md" in f for f in failures)


def test_a_module_claimed_by_two_groups_fails(gate) -> None:
    failures = gate.audit(ledger(group(), group(id="other", modules=["a.b"])), {"a.b"}, SUBSYSTEMS)
    assert any("claimed by both memory-bits and other" in f for f in failures)


def test_an_invented_disposition_fails(gate) -> None:
    failures = gate.audit(ledger(group(disposition="MAYBE")), {"a.b"}, SUBSYSTEMS)
    assert any("'MAYBE' is not one of" in f for f in failures)


def test_the_shipped_ledger_accounts_for_the_shipped_baseline(gate) -> None:
    assert gate.main() == 0
