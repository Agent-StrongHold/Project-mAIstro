"""Tests for the acceptance-state debt ratchet (#31).

`check-ac-state.py` measures how far each completion claim outruns its evidence.
Measuring was the easy half; the half that holds a line is failing when a
counter moves. These pin both directions, the mode guard, and the property that
a wrong-mode invocation cannot damage the committed measurement.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-ac-state.py"

TOTALS = {
    "completion_claims_contradicted": 9,
    "completion_claims_unverifiable": 68,
    "specs_awaiting_retrofit": 139,
    "markers_without_criterion": 2,
    "criteria_claimed_but_unproven": 0,
    "scenarios_without_ac_tag": 0,
    "gherkin_parse_errors": 0,
    # The absent-direction counters (#164).
    "specs_implementing_nothing": 76,
    "decided_adrs_without_spec": 35,
    "specs_owing_criteria": 146,
}


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_ac_state", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ceilings(gate, tmp_path, monkeypatch):
    """Point the gate at a throwaway ceilings file."""
    path = tmp_path / "ac-state-ceilings.json"
    monkeypatch.setattr(gate, "CEILINGS", path)

    def write(**overrides):
        payload = {"measured_with_tests": True, "ceilings": {**TOTALS, **overrides}}
        path.write_text(json.dumps(payload))
        return path

    write.path = path
    return write


def test_every_ratcheted_counter_is_exercised(gate) -> None:
    """`_compare` reads `totals[name]` for every name in RATCHETED, so a counter
    missing from this fixture is a KeyError in the gate rather than a test that
    skips it. Adding a counter without adding it here would leave that counter
    untested while every case below still passed."""
    assert set(TOTALS) == set(gate.RATCHETED)


def test_sitting_exactly_on_the_ceilings_passes(gate, ceilings) -> None:
    ceilings()
    assert gate.ratchet(TOTALS, measured=True, bank=False) == 0


def test_a_new_contradiction_fails(gate, ceilings, capsys) -> None:
    ceilings()
    worse = {**TOTALS, "completion_claims_contradicted": 10}
    assert gate.ratchet(worse, measured=True, bank=False) == 1
    assert "10 exceeds the ceiling of 9" in capsys.readouterr().out


def test_an_unbanked_improvement_also_fails(gate, ceilings, capsys) -> None:
    """Slack a later regression could spend. The same weakness every count
    ceiling has, and the reason the vulture ledger stopped being one."""
    ceilings()
    better = {**TOTALS, "specs_awaiting_retrofit": 130}
    assert gate.ratchet(better, measured=True, bank=False) == 1
    out = capsys.readouterr().out
    assert "unbanked improvement" in out
    assert "130, ceiling still says 139" in out


def test_banking_an_improvement_then_passes(gate, ceilings) -> None:
    path = ceilings()
    better = {**TOTALS, "specs_awaiting_retrofit": 130}
    assert gate.ratchet(better, measured=True, bank=True) == 0
    assert json.loads(path.read_text())["ceilings"]["specs_awaiting_retrofit"] == 130
    assert gate.ratchet(better, measured=True, bank=False) == 0


def test_a_counter_with_no_ceiling_fails(gate, ceilings) -> None:
    path = ceilings()
    payload = json.loads(path.read_text())
    del payload["ceilings"]["gherkin_parse_errors"]
    path.write_text(json.dumps(payload))
    assert gate.ratchet(TOTALS, measured=True, bank=False) == 1


def test_comparing_across_measurement_modes_is_refused(gate, ceilings, capsys) -> None:
    """Without --run-tests nothing reaches the passing rung, so every claim above
    it reads as contradicted. Comparing anyway would make the gate's verdict
    depend on how it was invoked."""
    ceilings()
    assert gate.ratchet(TOTALS, measured=False, bank=False) == 1
    assert "re-run in that mode" in capsys.readouterr().out


def test_the_mode_guard_reports_before_anything_is_measured(gate, ceilings) -> None:
    """The guard exists so a wrong-mode run cannot overwrite the committed
    measurement with an unmeasured payload and only then complain."""
    ceilings()
    assert gate._mode_mismatch(run_tests=True) is None
    assert "Nothing was measured or written" in str(gate._mode_mismatch(run_tests=False))


def test_a_missing_ceilings_file_fails_with_the_bank_instruction(
    gate, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(gate, "CEILINGS", tmp_path / "absent.json")
    assert gate.ratchet(TOTALS, measured=True, bank=False) == 1
    assert "--ratchet --bank" in capsys.readouterr().out


def test_the_shipped_ceilings_cover_every_ratcheted_counter(gate) -> None:
    recorded = json.loads((ROOT / "quality" / "ac-state-ceilings.json").read_text())
    assert set(recorded["ceilings"]) == set(gate.RATCHETED)
    assert recorded["measured_with_tests"] is True
