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
    "specs_implementing_nothing": 76,
    "adrs_without_implementing_spec": 35,
    "specs_declaring_no_criteria": 7,
    # The one counter that is a percentage and the one whose recorded number is
    # a floor rather than a ceiling. A round 4.0 here rather than the shipped
    # 3.9582, so a test asserting on the direction reads as arithmetic about
    # floors and not as a second copy of the corpus measurement.
    "design_coverage": 4.0,
}


def test_the_fixture_covers_every_ratcheted_counter(gate):
    """A missing key here surfaces as a `KeyError` inside the gate.

    `_bank` and `_compare` both index `totals[name]` for every ratcheted
    counter, so a fixture that has fallen behind fails five tests at once with a
    traceback that points at the gate rather than at the fixture. Naming the
    drift directly is the difference between a five-minute fix and a confusing
    one — which is the same argument the gate itself makes about ceilings.
    """
    bounded = {*gate.RATCHETED, *gate.FLOORED}
    assert bounded == set(TOTALS), "TOTALS is missing: " + ", ".join(sorted(bounded - set(TOTALS)))


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
    assert set(recorded["ceilings"]) == {*gate.RATCHETED, *gate.FLOORED}
    assert recorded["measured_with_tests"] is True


class TestTheFloorUnderProgress:
    """`design_coverage` is the first counter where higher is better (#166).

    `_compare` compared ten counters in one direction before this, so the
    failure mode worth pinning is not "the floor does not work" but "the floor
    is quietly a ceiling" — a fall reported as an improvement to bank, which
    would ratchet the number *down* on every PR that lost ground and call it
    progress. These assert on which list each move lands in, not merely that
    something failed.
    """

    def test_design_coverage_is_floored_and_not_also_a_debt_counter(self, gate) -> None:
        """The membership assertion comes first because `isdisjoint` alone is
        vacuously true when `FLOORED` is empty — which is exactly the state the
        predicted bug leaves it in."""
        assert "design_coverage" in gate.FLOORED
        assert "design_coverage" not in gate.RATCHETED
        assert set(gate.RATCHETED).isdisjoint(gate.FLOORED)

    def test_a_fall_is_a_regression_and_names_the_floor(self, gate, ceilings, capsys) -> None:
        ceilings()
        worse = {**TOTALS, "design_coverage": 3.9}
        assert gate.ratchet(worse, measured=True, bank=False) == 1
        out = capsys.readouterr().out
        assert "3.9 falls below the floor of 4.0" in out
        assert "unbanked improvement" not in out, "a fall was offered as progress to bank"

    def test_a_rise_is_an_unbanked_improvement_not_a_regression(
        self, gate, ceilings, capsys
    ) -> None:
        """Proving a criterion must not read as a new contradiction."""
        ceilings()
        better = {**TOTALS, "design_coverage": 4.5}
        assert gate.ratchet(better, measured=True, bank=False) == 1
        out = capsys.readouterr().out
        assert "4.5, floor still says 4.0" in out
        assert "exceeds the ceiling" not in out

    def test_banking_a_rise_raises_the_floor(self, gate, ceilings) -> None:
        path = ceilings()
        better = {**TOTALS, "design_coverage": 4.5}
        assert gate.ratchet(better, measured=True, bank=True) == 0
        assert json.loads(path.read_text())["ceilings"]["design_coverage"] == 4.5
        assert gate.ratchet(better, measured=True, bank=False) == 0
        # ...and the raised floor is what makes the old value a regression.
        assert gate.ratchet(TOTALS, measured=True, bank=False) == 1

    def test_a_missing_floor_fails_rather_than_defaulting_to_zero(self, gate, ceilings) -> None:
        """`ceilings.get(name)` is None for an absent key, and `0 < None` raises
        while `actual > None` would too — but a `0` default would silently pass
        anything. The absence has to be its own failure."""
        path = ceilings()
        payload = json.loads(path.read_text())
        del payload["ceilings"]["design_coverage"]
        path.write_text(json.dumps(payload))
        assert gate.ratchet(TOTALS, measured=True, bank=False) == 1
