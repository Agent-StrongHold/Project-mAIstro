"""Behavioral tests for check_structural_violations."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.codebase.index import InMemoryCodeStructureIndex
from maistro.codebase.types import CodeImport, CodeModule, CodeStructureReport
from maistro.codebase.violations import check_structural_violations
from maistro.types.feedback import ClaimProvenance, Severity, ViolationCategory

FIXTURES_ROOT = Path(__file__).parent / "fixtures"


def test_none_report_yields_no_findings() -> None:
    assert check_structural_violations(None) == []


@pytest.mark.asyncio
async def test_bad_impl_flagged_as_di_violation() -> None:
    report = await InMemoryCodeStructureIndex().build(str(FIXTURES_ROOT))
    findings = check_structural_violations(report)
    di_findings = [f for f in findings if f.category is ViolationCategory.DI_VIOLATION]
    assert len(di_findings) == 1
    finding = di_findings[0]
    assert finding.severity is Severity.CRITICAL
    assert finding.provenance is ClaimProvenance.EXTRACTED
    assert "impls.bad_impl" in finding.file_path or "bad_impl" in finding.file_path


@pytest.mark.asyncio
async def test_good_impl_alone_has_no_di_violation() -> None:
    report = await InMemoryCodeStructureIndex().build(str(FIXTURES_ROOT))
    good_only = CodeStructureReport(
        root_path=report.root_path,
        modules=tuple(m for m in report.modules if m.module_path != "impls.bad_impl"),
    )
    findings = check_structural_violations(good_only)
    assert findings == []


def test_mutual_import_flagged_as_circular_import() -> None:
    mod_a = CodeModule(
        module_path="a",
        file_path="a.py",
        imports=(CodeImport(module="b", names=("thing",), line_number=1),),
    )
    mod_b = CodeModule(
        module_path="b",
        file_path="b.py",
        imports=(CodeImport(module="a", names=("other",), line_number=1),),
    )
    report = CodeStructureReport(root_path="/fake", modules=(mod_a, mod_b))
    findings = check_structural_violations(report)
    circular = [f for f in findings if f.category is ViolationCategory.CIRCULAR_IMPORT]
    assert len(circular) == 1
    assert circular[0].severity is Severity.HIGH
    assert circular[0].provenance is ClaimProvenance.EXTRACTED


def test_no_cycle_yields_no_circular_import_finding() -> None:
    mod_a = CodeModule(
        module_path="a",
        file_path="a.py",
        imports=(CodeImport(module="b", names=("thing",), line_number=1),),
    )
    mod_b = CodeModule(module_path="b", file_path="b.py")
    report = CodeStructureReport(root_path="/fake", modules=(mod_a, mod_b))
    findings = check_structural_violations(report)
    assert [f for f in findings if f.category is ViolationCategory.CIRCULAR_IMPORT] == []
