#!/usr/bin/env python3
"""Gate: every cross-package import names something that exists (#293).

What it catches
---------------
`packages/hive-conductor/backend/services/design_service.py` imported
`maistro_design.systems.builtins` — a module that has never existed in any
version of that package. Nothing noticed, because the import sat inside a bare
`except Exception` that substituted a hand-built design system carrying the same
slug as a real one. The Conductor shipped for months registering one stub where
six real Tier-1 systems belong.

Every gate in this repository looked at that code and passed. `ruff` and `mypy`
do not resolve imports across packages that are not installed in the checking
environment; the tests exercised the fallback path and asserted it produced a
system, which it did. The import was wrong in a way only a resolver could see.

So this resolves them, statically, against the source trees in this workspace:

- **The module must exist.** `maistro_design.systems.builtins` has no file, and
  that is the whole bug.
- **The imported name must exist in it.** `from x import y` where `x` resolves
  but has no `y` is the same defect one level down — and the one a typo makes.
  A name counts as present if the target module defines it *or* imports it,
  because `__init__.py` re-export is how most of these packages present an API.

Static on purpose
-----------------
No importing, so a module with a side effect at import time cannot run here, and
a package that is not installed in this environment is still checked. That last
part matters: hive-conductor is a flat-layout app whose wheel is deliberately
absent from `verify-wheel-imports.py`, so a runtime check would skip precisely
the package this was written for.

Two scopes, not one
-------------------
A name bound under `if TYPE_CHECKING:` exists for a type checker and **not at
runtime** -- that block never executes. So the scope a name must be found in
depends on the importer: an import that itself sits under `TYPE_CHECKING` may
resolve against either, and a runtime import must find a runtime name.

Collapsing the two is a false green, and there is a live instance.
`maistro/archive/__init__.py` declares `S3ArchiveStore` under `TYPE_CHECKING`
and serves it at runtime from a `__getattr__`; a resolver that accepted the
type-only binding would pass a runtime import even if that `__getattr__` were
deleted.

`__getattr__` lazy exports
--------------------------
A module defining module-level `__getattr__` can produce names no static read
finds. Rather than guess, this trusts that module's `__all__`: a name it
publishes is treated as present at runtime. A module with `__getattr__` and no
`__all__` publishes nothing this can verify, and its names are reported.

(An earlier version of this docstring claimed such exports were absent from
these packages. They are not -- `maistro.archive` has had one all along.)

The escape hatch
----------------
`# cross-package-imports: allow <reason>` on the import line or the line above.
Mandatory reason, so the waiver is reviewable in the diff.

Usage
-----
    python3 scripts/check-cross-package-imports.py
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = REPO_ROOT / "packages"

WAIVER = re.compile(r"#\s*cross-package-imports:\s*allow\s+(?P<reason>\S.*)")

#: Directories that are not first-party source to check *from*.
_SKIP_PARTS = {".venv", "node_modules", "__pycache__", "build", "dist", ".git"}


def source_roots() -> dict[str, Path]:
    """Top-level package name -> the directory its modules live under.

    Both layouts this monorepo uses: `packages/<dist>/src/<pkg>/` for the
    published libraries, and `packages/hive-conductor/backend/` for the flat app.
    Only the former can be *imported* by name, so only the former is a target.
    """
    roots: dict[str, Path] = {}
    for src in sorted(PACKAGES.glob("*/src")):
        for pkg in sorted(src.iterdir()):
            if pkg.is_dir() and (pkg / "__init__.py").is_file():
                roots[pkg.name] = pkg
    return roots


def _module_file(root: Path, parts: list[str]) -> Path | None:
    """The file backing `root.parts`, as a module or a package."""
    if not parts:
        return root / "__init__.py"
    base = root.joinpath(*parts)
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    candidate = base.with_suffix(".py")
    return candidate if candidate.is_file() else None


def _imported_by(node: ast.Import | ast.ImportFrom) -> set[str]:
    """The names one import statement binds locally.

    `import a.b` binds `a`; `from a import b` binds `b`; `as` renames either.
    """
    if isinstance(node, ast.Import):
        return {alias.asname or alias.name.split(".")[0] for alias in node.names}
    return {alias.asname or alias.name for alias in node.names}


def _assigned_by(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> set[str]:
    """The names one assignment binds, tuple and starred targets included."""
    if isinstance(node, ast.Assign):
        return {
            sub.id
            for target in node.targets
            for sub in ast.walk(target)
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store)
        }
    return {node.target.id} if isinstance(node.target, ast.Name) else set()


def _bound_by(node: ast.stmt, names: set[str]) -> None:
    """Record the names one module-scope statement binds."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        names.add(node.name)
    elif isinstance(node, ast.Import | ast.ImportFrom):
        names |= _imported_by(node)
    elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
        names |= _assigned_by(node)


def _is_type_checking(test: ast.expr) -> bool:
    """Whether an `if` guards a type-checking-only block.

    Both spellings this repository uses: bare `TYPE_CHECKING` and
    `typing.TYPE_CHECKING`.
    """
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _collect(body: list[ast.stmt], runtime: set[str], type_only: set[str]) -> None:
    """Walk module scope, sorting names by the scope they actually exist in.

    `try: ... except ImportError:` and `with` are still module scope and still
    run, so names bound there are runtime names. An `if TYPE_CHECKING:` body
    does **not** run -- its names go to `type_only`, and only an importer that
    is itself under `TYPE_CHECKING` may use them.

    A function or class body opens a new scope and is not walked at all.
    """
    for node in body:
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            # The guarded body is type-only; its `else` still runs.
            _collect(node.body, type_only, type_only)
            _collect(node.orelse, runtime, type_only)
            continue
        _bound_by(node, runtime)
        if isinstance(node, ast.If | ast.Try | ast.With | ast.For | ast.While):
            for attr in ("body", "orelse", "finalbody"):
                _collect(getattr(node, attr, []) or [], runtime, type_only)
            for handler in getattr(node, "handlers", []) or []:
                _collect(handler.body, runtime, type_only)


@dataclass(frozen=True)
class Presented:
    """What one module presents, split by the scope a name exists in."""

    runtime: frozenset[str]
    type_only: frozenset[str]

    def has(self, name: str, *, under_type_checking: bool) -> bool:
        if name in self.runtime:
            return True
        return under_type_checking and name in self.type_only


@cache
def _names_in(path: Path) -> Presented:
    """Every name a module presents, and in which scope.

    Imported counts because `__init__.py` re-export is how these packages
    publish an API, and refusing that would flag every legitimate facade.

    **Module scope only.** An earlier version walked the whole tree, so a local
    variable inside a function counted as a module attribute and
    `from target import local_name` resolved against something no importer can
    reach -- the exact missing-attribute case this gate exists to catch, passing
    it (#413).

    **Type-only names are kept apart** (#413 review). `if TYPE_CHECKING:` never
    executes, so a name bound only there is not a runtime attribute;
    `maistro.archive` declares `S3ArchiveStore` that way and serves it from a
    `__getattr__`. Accepting the type-only binding for a runtime import would
    pass even with that `__getattr__` deleted.

    **`__getattr__` is trusted only as far as `__all__`.** A module with a
    module-level `__getattr__` can produce names no static read finds, so the
    names it publishes in `__all__` count as runtime-present. Without an
    `__all__` it publishes nothing verifiable and its names are reported.

    Cached: the same target is asked about once per importing statement, and a
    handful of facades are imported from hundreds of files. Uncached, a full
    scan re-parsed those hundreds of times.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return Presented(frozenset(), frozenset())
    runtime: set[str] = set()
    type_only: set[str] = set()
    _collect(tree.body, runtime, type_only)
    if "__getattr__" in runtime:
        runtime |= _declared_all(tree)
    return Presented(frozenset(runtime), frozenset(type_only))


def _declared_all(tree: ast.Module) -> set[str]:
    """The string literals in a module-level `__all__`, if it declares one."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        if isinstance(node.value, ast.List | ast.Tuple):
            return {
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    return set()


@dataclass(frozen=True)
class Finding:
    source: str
    line_no: int
    target: str
    reason: str

    def render(self) -> str:
        return f"  {self.source}:{self.line_no}\n    {self.target}\n    {self.reason}"


def _is_waived(lines: list[str], index: int) -> bool:
    candidates = [lines[index]]
    if index > 0:
        candidates.append(lines[index - 1])
    return any(WAIVER.search(candidate) for candidate in candidates)


def _imports_in(tree: ast.AST) -> list[tuple[int, str, list[str], bool]]:
    """Every absolute import, as `(line, dotted, names, under_type_checking)`.

    The flag decides which scope the target must present the name in: an import
    inside `if TYPE_CHECKING:` only has to satisfy a type checker, so a
    type-only binding is enough for it and not for anything else.

    Relative imports resolve inside their own package, where the interpreter and
    the test suite already catch a wrong one; they are not this gate's business.
    """
    out: list[tuple[int, str, list[str], bool]] = []

    def walk(node: ast.AST, *, type_checking: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and _is_type_checking(child.test):
                for item in child.body:
                    walk(item, type_checking=True)
                for item in child.orelse:
                    walk(item, type_checking=type_checking)
                continue
            if isinstance(child, ast.ImportFrom):
                if not child.level and child.module:
                    out.append(
                        (child.lineno, child.module, [a.name for a in child.names], type_checking)
                    )
            elif isinstance(child, ast.Import):
                out.extend((child.lineno, alias.name, [], type_checking) for alias in child.names)
            walk(child, type_checking=type_checking)

    walk(tree, type_checking=False)
    return out


def _resolve(
    root: Path,
    rest: list[str],
    dotted: str,
    imported: list[str],
    *,
    under_type_checking: bool = False,
) -> list[tuple[str, str]]:
    """Why `dotted` (and each name in it) fails to resolve under `root`.

    Empty means it resolves. Returned as `(what, why)` pairs rather than
    `Finding`s so the caller owns the file and line, and this stays a pure
    question about a source tree.
    """
    target = _module_file(root, rest)
    if target is None:
        return [(dotted, "no such module in the workspace source tree")]
    present = _names_in(target)
    reasons: list[tuple[str, str]] = []
    for name in imported:
        if name == "*":
            continue
        # A submodule is importable by name even when the package's __init__
        # never mentions it.
        if present.has(name, under_type_checking=under_type_checking):
            continue
        if _module_file(root, [*rest, name]) is not None:
            continue
        why = f"`{dotted}` exists but presents no `{name}`"
        if name in present.type_only:
            why = (
                f"`{dotted}` binds `{name}` only under TYPE_CHECKING, which does not "
                "run; this import does"
            )
        reasons.append((f"{dotted}.{name}", why))
    return reasons


def scan(path: Path, roots: dict[str, Path], repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Every unresolvable first-party import in one file.

    `repo_root` only shortens the reported path. It is a parameter rather than
    the module global so a caller can scan a tree that is not this repository --
    which the tests do, and which a global would make them mutate.
    """
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    rel = str(path.relative_to(repo_root))

    found: list[Finding] = []
    for line_no, dotted, imported, type_checking in _imports_in(tree):
        top, *rest = dotted.split(".")
        root = roots.get(top)
        if root is None:
            continue  # third-party or stdlib
        index = line_no - 1
        if index < len(lines) and _is_waived(lines, index):
            continue
        found.extend(
            Finding(rel, line_no, what, why)
            for what, why in _resolve(
                root, rest, dotted, imported, under_type_checking=type_checking
            )
        )
    return found


#: Trees outside `packages/` that are still first-party Python.
#:
#: The docstring below promised "every first-party Python file, tests
#: included", and the scan globbed `packages/` only -- so the repository's own
#: root `tests/`, `scripts/` and Alembic trees were outside a check advertised
#: as covering them, including the very `pytest.raises` paths the reason names
#: (#413). `tools/` joined them on review: it holds first-party importers too
#: (`tools/benchmark_execution_runtime.py` imports `maistro.runtime`) and one
#: of its scripts is run by a workflow, so leaving it out kept the same
#: overclaim alive one directory over.
_EXTRA_ROOTS = ("tests", "scripts", "tools", "alembic", "formal")


def source_files() -> list[Path]:
    """Every first-party Python file, tests included.

    Tests too: a test importing a module that does not exist fails loudly, but
    one importing a *name* that does not exist can sit inside a `pytest.raises`
    or a skip and never say so.

    `scripts/` too, for the same reason one layer up: a gate that cannot import
    what it names is a gate that does not run, and #262 is the record of what
    an absent check looks like from the outside.
    """
    trees = [PACKAGES, *(REPO_ROOT / name for name in _EXTRA_ROOTS)]
    files: list[Path] = []
    for tree in trees:
        if not tree.is_dir():
            continue
        for path in sorted(tree.rglob("*.py")):
            if _SKIP_PARTS.intersection(path.parts):
                continue
            files.append(path)
    return files


def main() -> int:
    roots = source_roots()
    if not roots:
        sys.stderr.write(f"no first-party packages found under {PACKAGES}\n")
        return 1
    files = source_files()
    if not files:
        sys.stderr.write("no first-party Python files found\n")
        return 1

    findings = [f for path in files for f in scan(path, roots, REPO_ROOT)]
    if findings:
        print(f"FAIL: {len(findings)} cross-package import(s) name something that does not exist\n")
        for finding in findings:
            print(finding.render())
            print()
        print(
            "An import that cannot resolve is not caught by ruff or mypy across\n"
            "packages that are not installed here, and a broad `except ImportError`\n"
            "turns it into product behaviour. See #293.\n"
            "Waive with: # cross-package-imports: allow <reason>"
        )
        return 1

    print(
        f"ok: {len(files)} file(s) import only modules and names that exist in {len(roots)} package(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
