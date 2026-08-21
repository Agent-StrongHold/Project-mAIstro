"""Structural violation checks: produces ReviewFindings from a CodeStructureReport.

Used by the Builders review gate as deterministic ground truth, alongside (and
able to outrank) the Auditor's LLM self-report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.types.feedback import ClaimProvenance, ReviewFinding, Severity, ViolationCategory

if TYPE_CHECKING:
    from maistro.codebase.types import CodeStructureReport

_EXEMPT_MODULE_PARTS = frozenset({"protocols", "tests"})


def _is_exempt(module_path: str) -> bool:
    return any(part in _EXEMPT_MODULE_PARTS for part in module_path.split("."))


def _check_concrete_imports_where_protocol_exists(
    report: CodeStructureReport,
) -> list[ReviewFinding]:
    """Flag a module that imports a concrete class by name where a same-named Protocol exists.

    Necessarily a name-based heuristic (no full type-checker MRO resolution from
    bare AST) — only fires when the imported symbol resolves to a concrete
    (non-Protocol) class inside the indexed report, to avoid false positives on
    unresolvable third-party imports that happen to share a Protocol's name.
    """
    protocol_names = {cls.name for _, cls in report.protocol_classes()}
    findings: list[ReviewFinding] = []
    for mod in report.modules:
        if _is_exempt(mod.module_path):
            continue
        for imp in mod.imports:
            target = report.module(imp.module)
            if target is None:
                continue
            for name in imp.names:
                if name not in protocol_names:
                    continue
                concrete_cls = next((cls for cls in target.classes if cls.name == name), None)
                if concrete_cls is None or concrete_cls.is_protocol:
                    continue
                findings.append(
                    ReviewFinding(
                        category=ViolationCategory.DI_VIOLATION,
                        severity=Severity.CRITICAL,
                        file_path=mod.file_path,
                        line_number=imp.line_number,
                        description=(
                            f"{mod.module_path} imports concrete class '{name}' directly from "
                            f"'{imp.module}', bypassing the '{name}' Protocol."
                        ),
                        suggestion=(
                            f"Depend on the Protocol abstraction instead of importing "
                            f"'{name}' directly (Protocol-driven DI)."
                        ),
                        provenance=ClaimProvenance.EXTRACTED,
                    )
                )
    return findings


def _check_circular_imports(report: CodeStructureReport) -> list[ReviewFinding]:
    """Flag circular imports among modules within the indexed report via a three-color DFS."""
    adjacency: dict[str, set[str]] = {
        mod.module_path: {imp.module for imp in mod.imports} for mod in report.modules
    }
    color: dict[str, int] = dict.fromkeys(adjacency, 0)
    findings: list[ReviewFinding] = []
    seen_cycles: set[frozenset[str]] = set()

    def _dfs(name: str, path: list[str]) -> None:
        color[name] = 1
        for dep in adjacency.get(name, ()):
            if dep not in color:
                continue
            if color[dep] == 1:
                cycle = [*path[path.index(dep) :], dep]
                key = frozenset(cycle)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    mod = report.module(name)
                    findings.append(
                        ReviewFinding(
                            category=ViolationCategory.CIRCULAR_IMPORT,
                            severity=Severity.HIGH,
                            file_path=mod.file_path if mod else "",
                            description=f"Circular import detected: {' -> '.join(cycle)}",
                            suggestion=(
                                "Break the cycle by extracting a shared abstraction or moving "
                                "the import inside a function/TYPE_CHECKING block."
                            ),
                            provenance=ClaimProvenance.EXTRACTED,
                        )
                    )
            elif color[dep] == 0:
                _dfs(dep, [*path, dep])
        color[name] = 2

    for name in adjacency:
        if color[name] == 0:
            _dfs(name, [name])
    return findings


def check_structural_violations(report: CodeStructureReport | None) -> list[ReviewFinding]:
    """Check a CodeStructureReport for structural violations and return findings.

    Returns an empty list if the report is None.
    """
    if report is None:
        return []
    return [
        *_check_concrete_imports_where_protocol_exists(report),
        *_check_circular_imports(report),
    ]
