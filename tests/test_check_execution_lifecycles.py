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
import json
import sys
from pathlib import Path
from types import SimpleNamespace

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

WORK_LITERAL = """
import typing
from typing_extensions import Literal as L

RunStatus: TypeAlias = typing.Literal[
    "pending",
    "running",
    "completed",
    "errored",
    "stopped",
] | None
QueueState = L["queued", "running", "failed"]
ConfigurationValues = typing.Literal["queued", "running", "failed"]
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


def test_literal_aliases_support_qualified_imports_pep604_and_split_values(gate) -> None:
    found = gate.work_state_literals(WORK_LITERAL, "pkg.jobs")
    assert found == {
        "pkg.jobs::RunStatus": {"PENDING", "RUNNING", "COMPLETED", "ERRORED", "STOPPED"},
        "pkg.jobs::QueueState": {"QUEUED", "RUNNING", "FAILED"},
    }


def test_literal_aliases_support_pep695_and_private_helper_aliases(gate) -> None:
    source = """
from typing import Literal

type _RunStates = Literal["queued", "running"]
RunStatus = _RunStates | Literal[
    "failed",
]
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {
        "pkg.jobs::RunStatus": {"QUEUED", "RUNNING", "FAILED"}
    }


def test_literal_field_annotations_are_discovered_without_broad_literal_noise(gate) -> None:
    source = """
import typing as t
from typing_extensions import Literal as L

_HelperStates = L["queued", "running", "failed"]

class Mission:
    status: t.Literal[
        "pending",
        "running",
        "completed",
        "failed",
    ]
    execution_status: _HelperStates
    kind: L["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {
        "pkg.jobs::Mission.status": {"PENDING", "RUNNING", "COMPLETED", "FAILED"},
        "pkg.jobs::Mission.execution_status": {"QUEUED", "RUNNING", "FAILED"},
    }


def test_the_real_rsi_literal_is_discovered(gate) -> None:
    found = gate.discover()
    assert found["services.rsi::RunStatus"] == {
        "PENDING",
        "RUNNING",
        "COMPLETED",
        "ERRORED",
        "STOPPED",
    }
    assert found["models.schemas::Mission.status"] == {
        "PENDING",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "PAUSED",
    }
    assert found["models.schemas::MissionStep.status"] == {
        "PENDING",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "SKIPPED",
    }
    assert found["maistro.orchestrator.waves.types::WaveHandle.status"] == {
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
    }


def test_literal_alias_requires_a_status_shaped_name(gate) -> None:
    source = 'from typing import Literal\nValues = Literal["queued", "running", "failed"]'
    assert gate.work_state_literals(source, "pkg.jobs") == {}


def test_literal_alias_with_two_work_states_is_below_signature(gate) -> None:
    source = 'from typing import Literal\nJobStatus = Literal["running", "failed"]'
    assert gate.work_state_literals(source, "pkg.jobs") == {}


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


def test_an_unclassified_literal_fails_by_name(gate) -> None:
    found = {"services.rsi::RunStatus": {"PENDING", "RUNNING", "COMPLETED"}}
    failures = gate.audit(ledger(), found)
    assert any("services.rsi::RunStatus" in f and "unclassified" in f for f in failures)


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


@pytest.mark.parametrize("classification", ["DOMAIN", "PROJECTION", "RECEIPT"])
def test_noncanonical_dispositions_are_allowed(gate, classification: str) -> None:
    found = {"pkg.jobs::JobStatus": {"PENDING", "RUNNING", "FAILED"}}
    assert (
        gate.audit(ledger(**{"pkg.jobs::JobStatus": entry(classification=classification)}), found)
        == []
    )


def test_a_new_canonical_literal_cannot_be_banked_by_its_ledger_entry(gate) -> None:
    name = "pkg.jobs::RunStatus"
    found = {name: {"PENDING", "RUNNING", "FAILED"}}
    assert gate.audit(ledger(**{name: entry(classification="CANONICAL")}), found) == []
    assert gate._unauthorized_additions([name], {}, set()) == [name]
    assert gate._unauthorized_additions([name], {}, {name}) == []


def test_main_rejects_an_unledgered_literal_source_fixture(
    gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise the production discovery path, not a fabricated ``found`` map."""
    source = tmp_path / "run_status.py"
    source.write_text(
        'from typing import Literal\nRunStatus = Literal["queued", "running", "failed"]\n',
        encoding="utf-8",
    )
    reachability = SimpleNamespace(
        FLAT_APPS=(),
        _collect_modules=lambda: {"fixture": source},
        _display_name=lambda key, _apps: key,
    )
    monkeypatch.setattr(gate, "_load_reachability", lambda: reachability)
    ledger_path = tmp_path / "execution-lifecycles.json"
    ledger_path.write_text(
        json.dumps({"metric_definition_version": "2", "lifecycles": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(gate, "LEDGER", ledger_path)

    class Baseline:
        base_sha = None

        def loads(self, default=None):
            return default

    class Receipt:
        def render(self) -> str:
            return "fixture provenance"

    provenance = SimpleNamespace(
        RatchetProvenanceError=RuntimeError,
        Provenance=lambda **_kwargs: Receipt(),
        resolve_baseline=lambda *_args, **_kwargs: Baseline(),
        require_measurement=lambda *_args, **_kwargs: None,
        require_metric_version=lambda *_args, **_kwargs: None,
        load_authorizations=lambda *_args, **_kwargs: {},
        head_sha=lambda *_args, **_kwargs: "fixture",
    )
    monkeypatch.setattr(gate, "_provenance", lambda: provenance)

    assert gate.main() == 1
    assert "fixture::RunStatus" in capsys.readouterr().out


def test_a_missing_rationale_fails(gate) -> None:
    found = {"pkg.jobs::JobStatus": {"PENDING", "RUNNING", "FAILED"}}
    failures = gate.audit(ledger(**{"pkg.jobs::JobStatus": entry(rationale="  ")}), found)
    assert "pkg.jobs::JobStatus: needs a rationale" in failures


def test_the_shipped_ledger_matches_the_shipped_code(
    gate, real_repository_ratchet_base: None
) -> None:
    assert gate.main() == 0
