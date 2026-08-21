"""Code-structure indexing: AST-derived snapshots of an arbitrary workspace root.

Builds a structural ground truth (imports, classes, Protocol membership) that
downstream checkers — e.g. the Builders review gate — can use instead of
relying solely on an LLM's self-reported review text.
"""

from __future__ import annotations

from maistro.codebase.index import InMemoryCodeStructureIndex
from maistro.codebase.python_parser import parse_python_module
from maistro.codebase.types import (
    CodeClass,
    CodeImport,
    CodeModule,
    CodeStructureReport,
)
from maistro.codebase.violations import check_structural_violations

__all__ = [
    "CodeClass",
    "CodeImport",
    "CodeModule",
    "CodeStructureReport",
    "InMemoryCodeStructureIndex",
    "check_structural_violations",
    "parse_python_module",
]
