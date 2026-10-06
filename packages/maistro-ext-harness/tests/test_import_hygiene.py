"""Import hygiene: the harness's own boundary, pinned like the SDK's (#974).

The harness is the tool that proves extensions depend only on public
contracts. It must not quietly depend on the product itself — its runtime
is the standard library, so a third-party CI can install the wheel and run
without any part of the monorepo. This test is the static half of that
promise (the wheel-level half is the repo's verify-wheel-imports gate).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "maistro_ext_harness"


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_runtime_imports_are_standard_library_only() -> None:
    """Every import in the shipped package resolves to the stdlib or to the
    package itself — the property that makes third-party CI installability
    real, and the boundary the namespace policy records."""
    assert SRC.is_dir(), f"harness source tree missing at {SRC}"
    first_party_allowed = {"maistro_ext_harness"}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for root in _import_roots(tree):
            if root in first_party_allowed:
                continue
            assert root in sys.stdlib_module_names, (
                f"{path.name} imports {root!r}: the harness runtime must stay standard-library only"
            )


def test_public_surface_has_no_underscore_escapes() -> None:
    """`__all__` names nothing underscore-private — private seams do not ride
    the public root, same rule the extension import gate enforces outward."""
    init = SRC / "__init__.py"
    tree = ast.parse(init.read_text(encoding="utf-8"))
    all_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "__all__":
                all_names = [
                    elt.value
                    for elt in node.value.elts  # type: ignore[attr-defined]
                    if isinstance(elt, ast.Constant)
                ]
    assert all_names, "__all__ disappeared from the package __init__"
    assert not [name for name in all_names if name.startswith("_")]
