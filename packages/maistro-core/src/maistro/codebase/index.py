"""In-memory code-structure index: walks a workspace root and parses every `.py` file."""

from __future__ import annotations

from pathlib import Path

from maistro.codebase.python_parser import parse_python_module
from maistro.codebase.types import CodeModule, CodeStructureReport

_SKIP_DIR_NAMES = frozenset(
    {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".pytest_cache"}
)


def _module_path_for(file_path: Path, root: Path) -> str:
    parts = list(file_path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class InMemoryCodeStructureIndex:
    """Builds a `CodeStructureReport` by walking a workspace root's `.py` files."""

    async def build(self, root_path: str) -> CodeStructureReport:
        root = Path(root_path)
        modules: list[CodeModule] = []
        for file_path in sorted(root.rglob("*.py")):
            if any(part in _SKIP_DIR_NAMES for part in file_path.parts):
                continue
            source = file_path.read_text(encoding="utf-8")
            module_path = _module_path_for(file_path, root)
            modules.append(
                parse_python_module(source, module_path=module_path, file_path=str(file_path))
            )
        return CodeStructureReport(root_path=root_path, modules=tuple(modules))
