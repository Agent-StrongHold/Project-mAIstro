#!/usr/bin/env python3
"""Gate: extension packages import only the public SDK (M9-A3, #951).

What this closes
----------------
The M9 epic (#938) publishes a versioned extension SDK so third parties can
extend MAIstro without importing product-private internals. A published SDK
enforces nothing by itself: nothing stopped an extension from
``from maistro.security.warden import _regex`` — a module that can be rewritten
or deleted between any two releases — or from ``sys.path.insert(0, "packages/")``
to reach a source tree that only exists in a development checkout. The boundary
was prose. This gate makes it a check.

The policy
----------
`extensions/namespace-policy.json` is the machine-readable half of the
boundary:

- ``public_sdk_namespaces`` — the first-party import roots an extension may
  use. Exactly one today: the versioned extension SDK package (M9-A1, #949).
- ``product_private_namespaces`` — first-party roots an extension must never
  import. Everything first-party not on the public list is here, and the gate
  checks the classification is *closed*: every import root shipped under
  ``packages/*/src`` must appear on exactly one list, so a new product package
  cannot become extension-importable by being forgotten.
- ``extension_trees`` — which directories are extension packages. Each must be
  its own buildable project (a ``pyproject.toml``), which is what keeps the
  tree outside the uv workspace and outside every product wheel.
- ``test_only_namespaces`` — roots a test file may import without declaring
  them as runtime dependencies. Outside the extension's top-level ``tests/``
  tree they are undeclared-dependency violations: test tooling is not a
  shipped dependency, and a ``tests`` package inside the shipped namespace is
  still product code.

What counts as a violation
--------------------------
Static, over every ``.py`` file in every extension tree — an import inside a
function, an ``if``, or ``if TYPE_CHECKING:`` is still a dependency (the same
call `packages/maistro-ext-sdk`'s own hygiene test makes about itself):

- importing a **product-private root** (anything on the private list, or any
  first-party root at all that is not the public SDK);
- importing a **underscore-prefixed module** even under a public root —
  ``maistro_ext_sdk._internal`` is a private seam wearing the SDK's name;
- importing a **repo-relative root** (``packages.*``, ``extensions.*``) or
  calling **``sys.path.insert``/``sys.path.append``** — repairing for the
  repository's layout is the import the isolation fixture exists to make
  impossible;
- calling ``importlib.import_module(...)`` / ``__import__(...)`` on a literal
  string that resolves to any of the above, directly or through an alias of
  the callable or its module (``from importlib import import_module as load;
  load("maistro")``) — a dynamic import is still an import, and reading it
  statically is what keeps this gate from needing to run any extension code;
- naming a **manifest ``entrypoint.module`` outside the extension's own
  packaged namespace** — a host imports that module as the extension's code,
  so ``maistro.security.warden`` as an entrypoint reaches a product-private
  module without a single Python ``import`` statement for the loop above to
  scan;
- importing a **third-party root the extension does not declare** in its own
  ``pyproject.toml`` — an undeclared import cannot survive a clean
  environment, which is the property the isolation fixture proves.

What it deliberately does not do
--------------------------------
It does not validate manifest *schemas* (that is the SDK package's job,
M9-A1) and does not decide grants (M9-A2). It reads the one boundary the epic
assigns this issue: which modules an extension may name — in Python imports
and, because a host imports it as extension code, in the manifest's
``entrypoint.module``.

Usage
-----
    python3 scripts/check-extension-imports.py
    python3 scripts/check-extension-imports.py --policy extensions/namespace-policy.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO_ROOT / "extensions" / "namespace-policy.json"

#: Import roots that are the repository's own layout rather than a module:
#: reaching across them means depending on the checkout, not on a release.
_REPO_RELATIVE_ROOTS = frozenset({"packages", "extensions"})

#: ``sys.path`` mutation calls that rescue repo-relative imports at runtime.
_SYS_PATH_METHODS = frozenset({"insert", "append", "extend"})

_DEP_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

_FIRST_PARTY_SRC = "packages/*/src"


@dataclass(frozen=True)
class Policy:
    """The parsed namespace policy (see the module docstring for the fields)."""

    policy_version: str
    public_sdk_namespaces: tuple[str, ...]
    product_private_namespaces: tuple[str, ...]
    extension_trees: tuple[str, ...]
    test_only_namespaces: tuple[str, ...]


@dataclass(frozen=True)
class Violation:
    """One disallowed import, named well enough to fix without re-running."""

    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        try:
            location = self.path.relative_to(REPO_ROOT)
        except ValueError:  # a fabricated tree outside the repo (the tests')
            location = self.path
        return f"{location}:{self.line}: {self.message}"


def load_policy(path: Path) -> Policy:
    """Read and validate the namespace policy file.

    Fails loudly on a policy that cannot decide: overlapping classifications,
    empty extension trees, or a missing file are configuration errors (exit 2),
    not passes.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"policy file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"policy file is not valid JSON: {path}: {exc}") from exc

    public = tuple(raw.get("public_sdk_namespaces", ()))
    private = tuple(raw.get("product_private_namespaces", ()))
    trees = tuple(raw.get("extension_trees", ()))
    test_only = tuple(raw.get("test_only_namespaces", ()))
    version = str(raw.get("policy_version", ""))

    overlap = sorted(set(public) & set(private))
    if overlap:
        raise SystemExit(
            f"policy classifies {overlap} as both public SDK and product-private; "
            "a namespace must be exactly one"
        )
    if not public:
        raise SystemExit(
            "policy declares no public_sdk_namespaces; extensions could import nothing"
        )
    if not trees:
        raise SystemExit("policy declares no extension_trees; nothing would be checked")

    return Policy(
        policy_version=version,
        public_sdk_namespaces=public,
        product_private_namespaces=private,
        extension_trees=trees,
        test_only_namespaces=test_only,
    )


def first_party_import_roots(repo_root: Path) -> set[str]:
    """Import roots shipped under ``packages/*/src``.

    Used to keep the policy closed: a first-party root that is on neither list
    is a policy gap, and a gap reads to an extension author exactly like a
    permission. Flat-layout trees (hive-conductor's backend) ship no single
    import root under ``src/`` and are outside this inventory by construction.
    """
    roots: set[str] = set()
    for init in sorted(repo_root.glob(f"{_FIRST_PARTY_SRC}/*/__init__.py")):
        roots.add(init.parent.name)
    return roots


def discover_extensions(repo_root: Path, policy: Policy) -> list[Path]:
    """Extension package directories, one per policy tree pattern.

    A matched directory without a ``pyproject.toml`` is not a project and
    cannot be built in a clean environment — reported as a policy error rather
    than silently skipped.
    """
    found: list[Path] = []
    for pattern in policy.extension_trees:
        matches = sorted(repo_root.glob(pattern))
        dirs = [match for match in matches if match.is_dir()]
        if not dirs:
            raise SystemExit(f"extension_trees pattern {pattern!r} matched no directory")
        for match in dirs:
            if not (match / "pyproject.toml").is_file():
                raise SystemExit(
                    f"extension {match.name} has no pyproject.toml; an extension must "
                    "be its own buildable project"
                )
            found.append(match)
    return found


def declared_dependencies(pyproject: Path) -> set[str]:
    """Runtime dependency names declared in an extension's ``pyproject.toml``."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps: set[str] = set()
    for dep in data.get("project", {}).get("dependencies", []):
        match = _DEP_NAME_RE.match(dep)
        if match:
            deps.add(match.group(1).replace("-", "_"))
    return deps


def own_import_root(pyproject: Path) -> str:
    """The import root an extension ships, from its wheel packages or its name."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    packages = (
        data.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("packages", [])
    )
    if packages:
        return str(packages[0]).split("/")[-1]
    name = str(data.get("project", {}).get("name", pyproject.parent.name))
    return name.replace("-", "_")


def _import_roots(tree: ast.AST) -> list[tuple[str | None, int, str]]:
    """Every module reference an import statement makes, with location and kind.

    Includes imports nested in functions, ``if`` blocks, and ``TYPE_CHECKING``
    guards — scope changes when a name binds, never whether it couples.
    Returns ``(root, lineno, detail)`` triples; a ``None`` root is a structural
    violation (a ``sys.path`` repair) that is disallowed by shape alone.
    """
    found: list[tuple[str | None, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name.split(".")[0], node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                # A relative import resolves inside the importing package, so
                # it can only name the extension's own code.
                continue
            if node.module:
                root = node.module.split(".")[0]
                names = ", ".join(alias.name for alias in node.names)
                found.append((root, node.lineno, f"from {node.module} import {names}"))
        elif isinstance(node, ast.Attribute):
            found.extend(_sys_path_mutation(node))
    found.extend(_DynamicImportCollector().visit_tree(tree).found)
    return found


_DYNAMIC_IMPORT_CALLABLES = frozenset({"import_module", "__import__"})
_DYNAMIC_IMPORT_MODULES = frozenset({"importlib", "builtins"})


class _ImportScope:
    """Names one lexical scope binds to the dynamic-import machinery."""

    def __init__(self) -> None:
        self.callables: set[str] = set()
        self.modules: set[str] = set()


class _DynamicImportCollector(ast.NodeVisitor):
    """Literal-string dynamic-import calls, with aliases resolved.

    Tracks which names each lexical scope binds to the real callables
    (``from importlib import import_module as load``, ``import importlib as
    il``) and classifies a call only through those bindings — never through
    the terminal attribute or name alone. ``load("maistro")`` is still an
    import, and ``manager.import_module("optional_plugin")`` is still just
    a method call.
    """

    def __init__(self) -> None:
        self.found: list[tuple[str | None, int, str]] = []
        self._scopes: list[_ImportScope] = [_ImportScope()]

    def visit_tree(self, tree: ast.AST) -> _DynamicImportCollector:
        self.visit(tree)
        return self

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scoped(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scoped(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scoped(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._scoped(node)

    def _scoped(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda
    ) -> None:
        # Decorators, defaults, and bases run in the enclosing scope; the
        # body binds fresh names.
        args = getattr(node, "args", None)
        outer: list[ast.AST] = [
            *getattr(node, "decorator_list", []),
            *(args.defaults if args else []),
            *(d for d in (args.kw_defaults if args else []) if d),
            *getattr(node, "bases", []),
        ]
        for child in outer:
            self.visit(child)
        self._scopes.append(_ImportScope())
        for stmt in node.body:
            self.visit(stmt)
        self._scopes.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _DYNAMIC_IMPORT_MODULES:
                self._scopes[-1].modules.add(alias.asname or root)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module in _DYNAMIC_IMPORT_MODULES:
            for alias in node.names:
                if alias.name in _DYNAMIC_IMPORT_CALLABLES:
                    self._scopes[-1].callables.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if node.args and self._is_dynamic_import(node.func):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                root = arg.value.split(".")[0]
                self.found.append((root, node.lineno, f'dynamic import of "{arg.value}"'))
        self.generic_visit(node)

    def _is_dynamic_import(self, func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            # ``__import__`` is a builtin even with no from-import in sight.
            return func.id == "__import__" or self._bound(func.id, "callables")
        if isinstance(func, ast.Attribute) and func.attr in _DYNAMIC_IMPORT_CALLABLES:
            return isinstance(func.value, ast.Name) and self._bound(func.value.id, "modules")
        return False

    def _bound(self, name: str, kind: str) -> bool:
        return any(name in getattr(scope, kind) for scope in self._scopes)


def _sys_path_mutation(node: ast.Attribute) -> list[tuple[str | None, int, str]]:
    """``sys.path.insert/append/extend`` — the repo-relative rescue hatch."""
    if node.attr not in _SYS_PATH_METHODS:
        return []
    value = node.value
    if isinstance(value, ast.Attribute) and value.attr == "path":
        inner = value.value
        if isinstance(inner, ast.Name) and inner.id == "sys":
            return [
                (None, node.lineno, f"sys.path.{node.attr}(...); extensions do not repair sys.path")
            ]
    return []


def scan_extension(extension_dir: Path, policy: Policy) -> list[Violation]:
    """Every policy violation in one extension tree.

    Per-file rules know the file's location: an import root allowed only in
    tests is a violation anywhere else, and the extension's own import root is
    always allowed.
    """
    pyproject = extension_dir / "pyproject.toml"
    deps = declared_dependencies(pyproject)
    own_root = own_import_root(pyproject)

    violations: list[Violation] = []
    for path in sorted(extension_dir.rglob("*.py")):
        if any(part in {"__pycache__", ".venv", "dist", "build"} for part in path.parts):
            continue
        # Only the extension's own top-level tests tree is test-only. A
        # ``tests`` package beneath the shipped namespace (``src/root/tests/``)
        # is product code a host can import — its imports need declaring.
        in_tests = path.relative_to(extension_dir).parts[0] == "tests"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for root, lineno, detail in _import_roots(tree):
            if root is None:
                violations.append(Violation(path, lineno, detail))
                continue
            violation = _classify(root, detail, policy, deps, own_root, in_tests)
            if violation is not None:
                violations.append(Violation(path, lineno, violation))
    violations.extend(manifest_entrypoint_violations(extension_dir, policy, own_root))
    return violations


def manifest_entrypoint_violations(
    extension_dir: Path, policy: Policy, own_root: str
) -> list[Violation]:
    """The manifest's ``entrypoint.module``, held to the same boundary as imports.

    A host imports this module as the extension's code, yet nothing in the
    tree needs to ``import`` it — so a manifest can name a product-private
    path (``maistro.security.warden``) or a repo-relative root and pass every
    Python-level scan while both gates stay green. The entrypoint must be code
    the extension itself ships: its own packaged import root, never a private
    or repo-relative one.
    """
    manifest = extension_dir / "extension.json"
    if not manifest.is_file():
        return []  # no entrypoint named; manifest absence is the artifact gate's
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [Violation(manifest, 1, f"unreadable extension manifest: {exc}")]

    entrypoint = data.get("entrypoint")
    module = entrypoint.get("module") if isinstance(entrypoint, dict) else None
    if not isinstance(module, str) or not module:
        return []  # an entrypoint must exist at all — that is schema, not boundary

    def violation(message: str) -> Violation:
        return Violation(manifest, _manifest_line(manifest, module), message)

    parts = module.split(".")
    root = parts[0]
    if root == own_root:
        if any(segment.startswith("_") for segment in parts[1:]):
            return [
                violation(
                    f"private entrypoint (entrypoint.module {module}); "
                    "underscore-prefixed modules are internal even within the "
                    "extension's own namespace"
                )
            ]
        return []
    if root in _REPO_RELATIVE_ROOTS:
        return [
            violation(
                f"repo-relative entrypoint (entrypoint.module {module}); extensions "
                "depend on releases, not checkouts"
            )
        ]
    if root in policy.product_private_namespaces:
        return [
            violation(
                f"product-private entrypoint (entrypoint.module {module}); a host "
                "imports this as extension code, and product-private modules are "
                "not stable for extensions"
            )
        ]
    return [
        violation(
            f"entrypoint outside the extension's own namespace (entrypoint.module "
            f"{module}; expected import root {own_root}); an entrypoint must be "
            "code the extension itself ships"
        )
    ]


def _manifest_line(manifest: Path, needle: str) -> int:
    """The line a manifest names a module on, so the violation points at it."""
    for lineno, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return lineno
    return 1


def _classify(
    root: str,
    detail: str,
    policy: Policy,
    deps: set[str],
    own_root: str,
    in_tests: bool,
) -> str | None:
    """The rule for one import root, or ``None`` when it is allowed."""
    if root == own_root:
        return None
    if root in sys.stdlib_module_names:
        return None
    if root in _REPO_RELATIVE_ROOTS:
        return f"repo-relative import ({detail}); extensions depend on releases, not checkouts"
    if root in policy.product_private_namespaces:
        return f"product-private import ({detail}); only the public SDK is stable for extensions"
    if root in policy.public_sdk_namespaces:
        return None  # module-level underscore privacy is checked by the caller
    if in_tests and root in policy.test_only_namespaces:
        return None
    if root.replace("-", "_") in deps:
        return None
    return f"undeclared third-party import ({detail}); add it to pyproject dependencies"


def _private_imports_in_tree(tree: ast.AST, public: set[str]) -> list[tuple[int, str]]:
    """``(lineno, message)`` for every underscore-private member import."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] in public and any(segment.startswith("_") for segment in parts[1:]):
                    found.append(
                        (
                            node.lineno,
                            f"private import ({alias.name}); underscore-prefixed modules "
                            "are internal even under a public SDK root",
                        )
                    )
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            if parts[0] not in public:
                continue
            # a private module can hide in the path itself
            # (``from root._internal import thing``), so inspect every
            # segment exactly as ast.Import does.
            private_module = any(segment.startswith("_") for segment in parts[1:])
            for alias in node.names:
                if private_module or alias.name.startswith("_"):
                    found.append(
                        (
                            node.lineno,
                            f"private import (from {node.module} import {alias.name}); "
                            "underscore-prefixed names are internal even under a "
                            "public SDK root",
                        )
                    )
    return found


def scan_private_modules(extension_dir: Path, public_roots: tuple[str, ...]) -> list[Violation]:
    """Underscore-prefixed members under a public SDK root are private.

    Kept as a separate pass so the rule is findable on its own: the public
    root is a promise about the namespace, not about every name inside it.
    Both spellings are checked — ``import root._internal`` names the private
    module in the path; ``from root import _helper`` names it in the alias.
    """
    violations: list[Violation] = []
    public = set(public_roots)
    for path in sorted(extension_dir.rglob("*.py")):
        if any(part in {"__pycache__", ".venv", "dist", "build"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, message in _private_imports_in_tree(tree, public):
            violations.append(Violation(path, lineno, message))
    return violations


def check_policy_closure(policy: Policy, repo_root: Path) -> None:
    """Every shipped first-party import root must be classified exactly once."""
    shipped = first_party_import_roots(repo_root)
    classified = set(policy.public_sdk_namespaces) | set(policy.product_private_namespaces)
    unclassified = sorted(shipped - classified)
    if unclassified:
        raise SystemExit(
            f"policy does not classify first-party import roots {unclassified}; "
            "add each to public_sdk_namespaces or product_private_namespaces"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    check_policy_closure(policy, REPO_ROOT)

    violations: list[Violation] = []
    for extension_dir in discover_extensions(REPO_ROOT, policy):
        violations.extend(scan_extension(extension_dir, policy))
        violations.extend(scan_private_modules(extension_dir, policy.public_sdk_namespaces))

    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(
            f"FAIL: {len(violations)} extension import violation(s) under {policy.extension_trees}",
            file=sys.stderr,
        )
        return 1

    extensions = discover_extensions(REPO_ROOT, policy)
    print(f"ok: {len(extensions)} extension package(s) import only the public SDK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
