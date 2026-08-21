"""Value types for code-structure indexing.

CodeImport/CodeClass/CodeModule are purely syntactic facts extracted from a
single Python source file. CodeStructureReport aggregates them across a
workspace root and exposes the lookups checkers need.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CodeImport:
    """A single import statement within a module."""

    module: str
    names: tuple[str, ...] = ()
    is_relative: bool = False
    line_number: int = 0


@dataclass(frozen=True)
class CodeClass:
    """A class definition within a module."""

    name: str
    bases: tuple[str, ...] = ()
    is_protocol: bool = False
    line_number: int = 0


@dataclass(frozen=True)
class CodeModule:
    """The structural facts extracted from a single Python source file."""

    module_path: str
    file_path: str
    imports: tuple[CodeImport, ...] = ()
    classes: tuple[CodeClass, ...] = ()
    parse_error: str = ""


@dataclass(frozen=True)
class CodeStructureReport:
    """A structural snapshot of every parsed module under a workspace root."""

    root_path: str
    modules: tuple[CodeModule, ...] = field(default_factory=tuple)

    def module(self, module_path: str) -> CodeModule | None:
        """Look up a module by its dotted module path."""
        for mod in self.modules:
            if mod.module_path == module_path:
                return mod
        return None

    def modules_importing(self, target_module: str) -> tuple[CodeModule, ...]:
        """Every module with an import statement naming ``target_module``."""
        return tuple(
            mod for mod in self.modules if any(imp.module == target_module for imp in mod.imports)
        )

    def protocol_classes(self) -> tuple[tuple[CodeModule, CodeClass], ...]:
        """Every (module, class) pair where the class is a Protocol."""
        return tuple((mod, cls) for mod in self.modules for cls in mod.classes if cls.is_protocol)
