"""The machine-readable conformance report (#974).

One JSON document per run. The report is the acceptance surface:

- it names the **exact contract version** enforced and the harness version
  that produced it (a reader can tell "manifest predates this host" from
  "malformed manifest");
- it lists **every case — executed, failed, or skipped — with its reason**;
  a skipped case is a named line, never an absence;
- it states, structurally, that this is a **local harness result and not
  platform certification**: no sandbox ran, no canonical
  `Goal -> Graph -> Run -> NodeRun -> Attempt` execution was created, no
  organization policy was evaluated, and no certification claim may be
  derived from this document.

Determinism: the report contains no timestamps or host specifics, so two
runs of the same subject against the same harness version are byte-stable
apart from nothing — comparable in any CI diff.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from maistro_ext_harness.contract import REPORT_SCHEMA

__all__ = [
    "CERTIFICATION_NOTE",
    "CaseRecord",
    "CaseStatus",
    "ConformanceReport",
    "SubjectRecord",
]

#: The one distinction every consumer must see: a harness pass is not a
#: certification. Worded for the report, referenced by the tests, so the
#: claim cannot quietly disappear from the artifact.
CERTIFICATION_NOTE = (
    "Local harness result over public contracts only. This is NOT platform "
    "certification: no sandbox executed, no canonical "
    "Goal->Graph->Run->NodeRun->Attempt evidence was created, and no "
    "organization policy was evaluated. Properties that require real "
    "backends did not execute unless a backend was registered and probed."
)


class CaseStatus(StrEnum):
    """The three honest outcomes. There is no fourth, silent one."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class SubjectRecord:
    """One extension the suite ran against."""

    role: str
    extension_id: str
    version: str
    family: str
    contract_range: str
    optional_features: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class CaseRecord:
    """One executed (or explicitly skipped) conformance case."""

    case_id: str
    family: str
    subject: str
    status: CaseStatus
    detail: str
    required_backend: str | None = None


@dataclass
class ConformanceReport:
    """The run's full result. Serialize with `to_dict` / `write_json`."""

    harness_version: str
    contract_version: str
    supported_contract_majors: tuple[int, ...]
    subjects: list[SubjectRecord] = field(default_factory=list)
    cases: list[CaseRecord] = field(default_factory=list)
    backend_waivers: tuple[str, ...] = ()

    @property
    def failed(self) -> list[CaseRecord]:
        return [case for case in self.cases if case.status is CaseStatus.FAILED]

    @property
    def skipped(self) -> list[CaseRecord]:
        return [case for case in self.cases if case.status is CaseStatus.SKIPPED]

    @property
    def passed_count(self) -> int:
        return sum(1 for case in self.cases if case.status is CaseStatus.PASSED)

    def to_dict(self) -> dict[str, Any]:
        """The report's JSON shape — versioned by `REPORT_SCHEMA`."""
        return {
            "report_schema": REPORT_SCHEMA,
            "harness_version": self.harness_version,
            "contract_version": self.contract_version,
            "supported_contract_majors": list(self.supported_contract_majors),
            "certification": {
                "platform_certified": False,
                "note": CERTIFICATION_NOTE,
            },
            "subjects": [asdict(subject) for subject in self.subjects],
            "subject_contracts": sorted({s.contract_range for s in self.subjects}),
            "cases": [{**asdict(case), "status": str(case.status.value)} for case in self.cases],
            "required_backends": sorted(
                {c.required_backend for c in self.cases if c.required_backend}
            ),
            "backend_waivers": list(self.backend_waivers),
            "summary": {
                "total": len(self.cases),
                "passed": self.passed_count,
                "failed": len(self.failed),
                "skipped": len(self.skipped),
            },
        }

    def write_json(self, path: Path) -> Path:
        """Write the machine-readable report; parents are created."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path
