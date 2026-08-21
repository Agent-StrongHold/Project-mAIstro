"""Pure AST-based extraction of structural facts from a single Python source file.

No filesystem I/O here — callers read the source text and pass it in. Walks the
whole tree (not just top-level statements) so imports/classes nested under
``if TYPE_CHECKING:`` blocks, functions, or other classes are still captured.
"""

from __future__ import annotations

import ast

from maistro.codebase.types import CodeClass, CodeImport, CodeModule


def _base_name(node: ast.expr) -> str:
    """Resolve a class base expression to its dotted name.

    Recurses through ``ast.Attribute`` so ``maistro.protocols.tools.ToolExecutor``
    renders as that full dotted string. Unrolls ``ast.Subscript`` (e.g.
    ``Protocol[T]``) to its underlying name. Anything else (a call, a string,
    etc.) resolves to ``""`` — callers treat that as "not a recognizable base".
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _base_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ""


def _is_protocol_base(name: str) -> bool:
    return name == "Protocol" or name.endswith(".Protocol")


def parse_python_module(source: str, *, module_path: str, file_path: str) -> CodeModule:
    """Extract imports and classes from ``source``.

    Returns a ``CodeModule`` with ``parse_error`` set (rather than raising) on
    a ``SyntaxError`` — a single unparseable file shouldn't abort a larger walk.
    """
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as exc:
        return CodeModule(module_path=module_path, file_path=file_path, parse_error=str(exc))

    imports: list[CodeImport] = []
    classes: list[CodeClass] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(CodeImport(module=alias.name, line_number=node.lineno))
        elif isinstance(node, ast.ImportFrom):
            imports.append(
                CodeImport(
                    module=node.module or "",
                    names=tuple(alias.name for alias in node.names),
                    is_relative=node.level > 0,
                    line_number=node.lineno,
                )
            )
        elif isinstance(node, ast.ClassDef):
            bases = tuple(_base_name(base) for base in node.bases)
            classes.append(
                CodeClass(
                    name=node.name,
                    bases=bases,
                    is_protocol=any(_is_protocol_base(base) for base in bases),
                    line_number=node.lineno,
                )
            )

    return CodeModule(
        module_path=module_path,
        file_path=file_path,
        imports=tuple(imports),
        classes=tuple(classes),
    )
