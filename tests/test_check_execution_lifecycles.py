"""Tests for the execution-lifecycle ledger gate (#36).

A second execution lifecycle rarely arrives as a decision — it arrives as an
enum. The properties worth pinning are that a new one fails until classified, a
stale entry fails until pruned, CONVERGE cannot be claimed without naming the
issue that removes it, and the detector is narrow enough not to cry wolf. That
last one matters most: a gate with false positives teaches people to bank
whatever it says, which would launder a real second lifecycle through a routine
update.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-execution-lifecycles.py"

WORK_ENUM = """
from enum import StrEnum

class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
"""


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_execution_lifecycles", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ledger(**entries) -> dict:
    return {"lifecycles": entries}


def entry(**overrides) -> dict:
    return {"classification": "DOMAIN", "rationale": "because", **overrides}


# --- detection ----------------------------------------------------------------


def test_a_work_state_enum_is_detected(gate) -> None:
    found = gate.work_state_enums(WORK_ENUM, "pkg.jobs")
    assert set(found) == {"pkg.jobs::JobStatus"}
    assert found["pkg.jobs::JobStatus"] == {"PENDING", "RUNNING", "FAILED"}


def test_two_work_states_is_below_the_signature(gate) -> None:
    """Narrowness is the whole design. Two members is an enumeration, not a
    lifecycle, and flooding the ledger would make banking reflexive."""
    source = WORK_ENUM.replace('    FAILED = "failed"\n', "")
    assert gate.work_state_enums(source, "pkg.jobs") == {}


def test_an_enum_of_unrelated_members_is_ignored(gate) -> None:
    source = """
from enum import StrEnum

class Colour(StrEnum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
"""
    assert gate.work_state_enums(source, "pkg.paint") == {}


def test_a_plain_class_with_work_state_attributes_is_ignored(gate) -> None:
    """Only enum subclasses are candidates; constants on a plain class are not
    a state machine."""
    source = """
class Names:
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
"""
    assert gate.work_state_enums(source, "pkg.names") == {}


def test_a_dotted_enum_base_is_recognised(gate) -> None:
    source = WORK_ENUM.replace("from enum import StrEnum", "import enum").replace(
        "(StrEnum)", "(enum.StrEnum)"
    )
    assert set(gate.work_state_enums(source, "pkg.jobs")) == {"pkg.jobs::JobStatus"}


def test_syntax_errors_do_not_crash_the_sweep(gate) -> None:
    assert gate.work_state_enums("def (:", "pkg.broken") == {}


# --- ledger -------------------------------------------------------------------


def test_a_classified_enum_passes(gate) -> None:
    found = {"pkg.jobs::JobStatus": {"PENDING", "RUNNING", "FAILED"}}
    assert gate.audit(ledger(**{"pkg.jobs::JobStatus": entry()}), found) == []


def test_an_unclassified_enum_fails_by_name(gate) -> None:
    found = {"pkg.jobs::JobStatus": {"PENDING", "RUNNING", "FAILED"}}
    failures = gate.audit(ledger(), found)
    assert any("pkg.jobs::JobStatus" in f and "unclassified" in f for f in failures)


def test_an_entry_whose_enum_is_gone_fails_until_pruned(gate) -> None:
    """The stale half. A ledger that keeps entries for deleted code holds slack
    a later regression with the same name would silently occupy."""
    failures = gate.audit(ledger(**{"pkg.gone::JobStatus": entry()}), {})
    assert any("no longer found in the code; prune it" in f for f in failures)


def test_converge_without_an_issue_fails(gate) -> None:
    found = {"pkg.jobs::JobStatus": {"PENDING", "RUNNING", "FAILED"}}
    failures = gate.audit(
        ledger(**{"pkg.jobs::JobStatus": entry(classification="CONVERGE")}), found
    )
    assert any("CONVERGE requires 'converged_by'" in f for f in failures)


def test_converge_with_an_issue_passes(gate) -> None:
    found = {"pkg.jobs::JobStatus": {"PENDING", "RUNNING", "FAILED"}}
    assert (
        gate.audit(
            ledger(**{"pkg.jobs::JobStatus": entry(classification="CONVERGE", converged_by="#41")}),
            found,
        )
        == []
    )


def test_an_invented_classification_fails(gate) -> None:
    found = {"pkg.jobs::JobStatus": {"PENDING", "RUNNING", "FAILED"}}
    failures = gate.audit(ledger(**{"pkg.jobs::JobStatus": entry(classification="FINE")}), found)
    assert any("'FINE' is not one of" in f for f in failures)


def test_a_missing_rationale_fails(gate) -> None:
    found = {"pkg.jobs::JobStatus": {"PENDING", "RUNNING", "FAILED"}}
    failures = gate.audit(ledger(**{"pkg.jobs::JobStatus": entry(rationale="  ")}), found)
    assert "pkg.jobs::JobStatus: needs a rationale" in failures


def test_the_shipped_ledger_matches_the_shipped_code(gate) -> None:
    assert gate.main() == 0
