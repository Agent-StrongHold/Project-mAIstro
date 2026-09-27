"""No second design product may register its own loop kinds (#790).

Goal and Rubric, when they exist, are ontology kinds. EvalRun and DesignRun
are not kinds: scores live on the producing Run, and there is no second
execution lifecycle. A class or registry call with one of those names outside
the ontology package is the competing product ADR-092726-1cfa forbids, as is
an Atelier package or page. The catalog slug ``atelier-zero`` is a design
system and is not that page.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract("behavioral")]

_ONTOLOGY_KINDS = frozenset({"Goal", "Rubric"})
_FORBIDDEN_EVERYWHERE = frozenset({"EvalRun", "DesignRun"})
_ONTOLOGY_PREFIX = "packages/maistro-core/src/maistro/ontology/"
_SKIP_PARTS = frozenset({"tests", "__pycache__", "mutants", "third_party", "node_modules", ".venv"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _production_roots(root: Path) -> list[Path]:
    packages = root / "packages"
    roots: list[Path] = []
    if not packages.is_dir():
        return roots
    for package in sorted(path for path in packages.iterdir() if path.is_dir()):
        for name in ("src", "backend"):
            candidate = package / name
            if candidate.is_dir():
                roots.append(candidate)
    return roots


def _python_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for base in roots:
        files.extend(
            path
            for path in base.rglob("*.py")
            if not any(part in _SKIP_PARTS for part in path.parts)
        )
    return files


def _class_violation(rel: str, node: ast.ClassDef, ontology_home: bool) -> list[str]:
    name = node.name
    if name in _FORBIDDEN_EVERYWHERE or (name in _ONTOLOGY_KINDS and not ontology_home):
        return [f"{rel}:{node.lineno}: class {name} is a competing design-loop kind"]
    return []


def _registered_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        called = func.id
    elif isinstance(func, ast.Attribute):
        called = func.attr
    else:
        return None
    if called not in {"register", "register_kind"}:
        return None
    candidate: ast.expr | None = call.args[0] if call.args else None
    if candidate is None:
        for keyword in call.keywords:
            if keyword.arg in {"kind", "name"}:
                candidate = keyword.value
                break
    if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
        return candidate.value
    return None


def _call_violation(rel: str, node: ast.Call, ontology_home: bool) -> list[str]:
    kind = _registered_name(node)
    if kind is None:
        return []
    if kind in _FORBIDDEN_EVERYWHERE or (kind in _ONTOLOGY_KINDS and not ontology_home):
        return [f"{rel}:{node.lineno}: register({kind!r}) is a competing design-loop kind"]
    return []


def _kind_violations(root: Path) -> list[str]:
    violations: list[str] = []
    for path in _python_files(_production_roots(root)):
        rel = path.relative_to(root).as_posix()
        ontology_home = rel.startswith(_ONTOLOGY_PREFIX)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                violations.extend(_class_violation(rel, node, ontology_home))
            elif isinstance(node, ast.Call):
                violations.extend(_call_violation(rel, node, ontology_home))
    return violations


def _product_identity_violations(root: Path) -> list[str]:
    violations: list[str] = []
    for relative in ("packages/maistro-atelier", "packages/atelier"):
        if (root / relative).exists():
            violations.append(f"{relative}: second design product package")
    packages = root / "packages"
    if not packages.is_dir():
        return violations
    violations.extend(
        f"{path.relative_to(root).as_posix()}: Atelier page is a second product"
        for path in packages.rglob("Atelier.tsx")
        if not any(part in _SKIP_PARTS for part in path.parts)
    )
    return violations


def test_product_modules_do_not_register_a_competing_design_kind() -> None:
    """A product module that invents Goal, Rubric, EvalRun, or DesignRun fails.

    Goal and Rubric may be declared only under ``maistro.ontology``. EvalRun
    and DesignRun may not be declared at all. ``Atelier.tsx`` and the
    ``maistro-atelier`` / ``atelier`` packages are a second app, not a host
    for this loop.
    """
    root = _repo_root()
    violations = _kind_violations(root) + _product_identity_violations(root)
    assert not violations, "\n".join(violations)
