"""Protocol for code-structure indexing.

CodeStructureIndex: builds a structural snapshot of an arbitrary workspace root.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro.codebase.types import CodeStructureReport


@runtime_checkable
class CodeStructureIndex(Protocol):
    """Builds a structural snapshot (imports, classes, Protocol membership) of a workspace root."""

    async def build(self, root_path: str) -> CodeStructureReport:
        """Walk `root_path` and return a CodeStructureReport of every parsed module."""
        ...
