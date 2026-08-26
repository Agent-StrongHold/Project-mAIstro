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

What it deliberately does not do
--------------------------------
Follow `__getattr__`-based lazy exports or names produced by `globals()`
assignment. Both are absent from these packages today; if one appears, the fix
is a waiver naming it, not a resolver that guesses.

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


def _collect(body: list[ast.stmt], names: set[str]) -> None:
    """Walk module scope, descending into the blocks that are still module scope.

    `if TYPE_CHECKING:`, `try: ... except ImportError:` and `with` are all used
    for conditional exports in these packages, so a name bound inside one is a
    real module attribute. A function or class body is not: it opens a new
    scope, and that is the whole distinction this function exists to draw.
    """
    for node in body:
        _bound_by(node, names)
        if isinstance(node, ast.If | ast.Try | ast.With | ast.For | ast.While):
            for attr in ("body", "orelse", "finalbody"):
                _collect(getattr(node, attr, []) or [], names)
            for handler in getattr(node, "handlers", []) or []:
                _collect(handler.body, names)


@cache
def _names_in(path: Path) -> frozenset[str]:
    """Every name a module presents at import time: defined or imported.

    Imported counts because `__init__.py` re-export is how these packages
    publish an API, and refusing that would flag every legitimate facade.

    **Module scope only.** An earlier version walked the whole tree, so a local
    variable inside a function counted as a module attribute and
    `from target import local_name` resolved against something no importer can
    reach -- the exact missing-attribute case this gate exists to catch, passing
    it (#413). A function body is a different scope; a module-level `if` or
    `try` is not, and both are walked.

    Cached because the same target is asked about once per importing statement,
    and a handful of facades (`maistro.types`, `maistro.protocols`) are imported
    from hundreds of files. Uncached, a full scan re-parsed those hundreds of
    times and took long enough under coverage to trip a 30-second test timeout.
    Safe: this is a one-shot process reading a tree nothing is writing to.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return frozenset()
    names: set[str] = set()
    _collect(tree.body, names)
    return frozenset(names)


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


def _imports_in(tree: ast.AST) -> list[tuple[int, str, list[str]]]:
    """Every absolute import in a parsed module, as `(line, dotted, names)`.

    Relative imports resolve inside their own package, where the interpreter and
    the test suite already catch a wrong one; they are not this gate's business.
    """
    out: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            out.append((node.lineno, node.module, [a.name for a in node.names]))
        elif isinstance(node, ast.Import):
            out.extend((node.lineno, alias.name, []) for alias in node.names)
    return out


def _resolve(
    root: Path, rest: list[str], dotted: str, imported: list[str]
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
        if name in present or _module_file(root, [*rest, name]) is not None:
            continue
        reasons.append((f"{dotted}.{name}", f"`{dotted}` exists but presents no `{name}`"))
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
    for line_no, dotted, imported in _imports_in(tree):
        top, *rest = dotted.split(".")
        root = roots.get(top)
        if root is None:
            continue  # third-party or stdlib
        index = line_no - 1
        if index < len(lines) and _is_waived(lines, index):
            continue
        found.extend(
            Finding(rel, line_no, what, why) for what, why in _resolve(root, rest, dotted, imported)
        )
    return found


#: Trees outside `packages/` that are still first-party Python.
#:
#: The docstring below promised "every first-party Python file, tests
#: included", and the scan globbed `packages/` only -- so the repository's own
#: root `tests/`, `scripts/` and Alembic trees were outside a check advertised
#: as covering them, including the very `pytest.raises` paths the reason names
#: (#413). Measured when they were added: 207 further files, zero new findings,
#: so the claim was the only thing that was wrong.
_EXTRA_ROOTS = ("tests", "scripts", "alembic", "formal")


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
