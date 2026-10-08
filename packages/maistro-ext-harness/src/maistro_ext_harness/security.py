"""The certification security checks over an extension's own sources (#975).

One question, asked statically so no extension code runs while asking it:
**does this extension build on the public extension contracts, or does it
reach for product-private internals, the repository checkout, or
dependencies it never declared?**

This is the same boundary ``scripts/check-extension-imports.py`` enforces
for in-repository extension trees (M9-A3, #951), restated inside the
harness so a third-party certification runs it anywhere:

- shipped imports resolve only to the standard library, the public SDK
  (``maistro_ext_sdk``), the extension's own package, or a declared
  dependency;
- a product-private first-party root is a violation — the policy lists is
  embedded below and the harness's test suite holds it equal to the
  repository's ``extensions/namespace-policy.json`` so the two statements
  cannot drift;
- an underscore-prefixed module under a public root is a private seam
  wearing a public name: violation;
- the repository-relative sentinels (``packages``, ``extensions``) and any
  ``sys.path`` mutation (insert/append/extend — the same set the
  repository's ``check-extension-imports.py`` gate rejects) are checkout
  repairs: violations;
- a dynamic import (``importlib.import_module`` / ``__import__``) on a
  literal naming a forbidden root is still an import: violation, including
  through an alias of the callable (``from importlib import import_module
  as load``) or an alias of the module itself (``import importlib as il``
  then ``il.import_module``);
- the manifest's entrypoint must name a module inside the extension's own
  package — a host imports that module as extension code, so an entrypoint
  is an import the manifest makes on the extension's behalf;
- a test file (anything under a ``tests/`` directory) may import pytest;
  anywhere else pytest is an undeclared dependency.

Findings roll up into :class:`~maistro_ext_harness.checks.CheckRecord` s —
one per rule, naming every offending file, line, and token, so a declined
certification is actionable before any install is attempted.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from maistro_ext_harness.checks import CheckRecord, CheckStatus

__all__ = [
    "PRODUCT_PRIVATE_ROOTS",
    "PUBLIC_SDK_ROOTS",
    "REPO_RELATIVE_ROOTS",
    "TEST_ONLY_ROOTS",
    "security_checks",
]

#: The first-party import roots an extension MAY use (the public SDK, #949).
PUBLIC_SDK_ROOTS: frozenset[str] = frozenset({"maistro_ext_sdk"})

#: The first-party import roots an extension must NEVER use. Mirrors
#: ``extensions/namespace-policy.json``'s ``product_private_namespaces``;
#: ``tests/test_certification.py`` asserts the two stay equal, the same way
#: the harness's manifest tests hold its contract statement to the
#: reference extension.
PRODUCT_PRIVATE_ROOTS: frozenset[str] = frozenset(
    {
        "maistro",
        "maistro_bootstrap",
        "maistro_canvas",
        "maistro_design",
        "maistro_evolve",
        "maistro_ext_harness",
        "maistro_registry",
        "maistro_rsi",
        "maistro_server",
        "maistro_turing",
    }
)

#: Repository layout directories. Reaching across them means depending on a
#: development checkout, not on a release.
REPO_RELATIVE_ROOTS: frozenset[str] = frozenset({"packages", "extensions"})

#: Import roots a *test* file may use without the project declaring them:
#: test tooling is not a shipped dependency.
TEST_ONLY_ROOTS: frozenset[str] = frozenset({"pytest"})

_DIST_NAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?")


def _normalize(name: str) -> str:
    return name.lower().replace("-", "_")


def declared_distributions(pyproject: Path) -> tuple[str, ...]:
    """Distribution names declared in ``pyproject.toml``'s dependency lists.

    Parses (never executes) ``[project.dependencies]`` and every
    ``[project.optional-dependencies]`` list, reducing each requirement
    string to its distribution name (extras/markers/version specifiers
    stripped). Returns an empty tuple when the file is missing; parse errors
    surface as a packaging check, not as a silently empty allowlist.
    """
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    project = data.get("project")
    if not isinstance(project, dict):
        return ()
    names: list[str] = []
    for requirement in project.get("dependencies", ()) or ():
        match = _DIST_NAME_RE.match(str(requirement).strip())
        if match:
            names.append(_normalize(match.group(0)))
    extras = project.get("optional-dependencies")
    if isinstance(extras, dict):
        for requirements in extras.values():
            if isinstance(requirements, list):
                for requirement in requirements:
                    match = _DIST_NAME_RE.match(str(requirement).strip())
                    if match:
                        names.append(_normalize(match.group(0)))
    return tuple(names)


@dataclass
class _ScanContext:
    """Everything one file's scan needs to classify an import."""

    root: Path
    declared: frozenset[str]
    own_packages: frozenset[str]
    dist_for_root: dict[str, list[str]]
    #: (file, line, rule, token, detail) findings, one per violation.
    findings: list[tuple[str, int, str, str, str]] = field(default_factory=list)

    def is_test_file(self, path: Path) -> bool:
        return "tests" in path.relative_to(self.root).parts

    def classify(self, root_name: str, path: Path, line: int) -> None:
        """Classify one imported root; record a finding when it is forbidden."""
        head = root_name.split(".")[0]
        if head in sys.stdlib_module_names:
            return
        if head in self.own_packages:
            self._check_private_segments(root_name, path, line, "the extension's own package")
            return
        if head in PUBLIC_SDK_ROOTS:
            self._check_private_segments(root_name, path, line, "the public SDK root")
            return
        if head in PRODUCT_PRIVATE_ROOTS:
            self.findings.append(
                (
                    str(path),
                    line,
                    "product-private-import",
                    root_name,
                    f"{head!r} is a product-private root; extensions build on "
                    f"the public SDK {sorted(PUBLIC_SDK_ROOTS)} only",
                )
            )
            return
        if head in REPO_RELATIVE_ROOTS:
            self.findings.append(
                (
                    str(path),
                    line,
                    "repo-relative-import",
                    root_name,
                    f"{head!r} is the repository's layout, not a module; "
                    "depending on it depends on a checkout",
                )
            )
            return
        self._classify_third_party(head, path, line)

    def _check_private_segments(self, root_name: str, path: Path, line: int, under: str) -> None:
        if any(segment.startswith("_") for segment in root_name.split(".")):
            self.findings.append(
                (
                    str(path),
                    line,
                    "private-module",
                    root_name,
                    f"underscore-prefixed modules are private seams even under {under}",
                )
            )

    def _classify_third_party(self, head: str, path: Path, line: int) -> None:
        """A third-party root: declared, distribution-mapped, test-only, or a
        violation ("declare it or remove it")."""
        if head in TEST_ONLY_ROOTS and self.is_test_file(path):
            return
        if _normalize(head) in self.declared:
            return
        distributions = self.dist_for_root.get(head, ())
        if any(_normalize(dist) in self.declared for dist in distributions):
            return
        self.findings.append(
            (
                str(path),
                line,
                "undeclared-dependency",
                head,
                f"import root {head!r} is not the standard library, the public "
                "SDK, the extension's own package, or a declared dependency — "
                "declare it in pyproject.toml [project.dependencies] or remove it",
            )
        )


@dataclass(frozen=True)
class _ImportBindings:
    """The names one module binds to dynamic-import machinery."""

    #: Local names that ARE a dynamic-import callable: the ``__import__``
    #: builtin, ``from importlib import import_module as load``, and
    #: ``load = importlib.import_module``.
    callables: frozenset[str]
    #: Local names bound to the ``importlib`` module object itself:
    #: ``import importlib`` and ``import importlib as il``. An attribute
    #: call through such a binding (``il.import_module(...)``) is exactly as
    #: dynamic as the dotted spelling; only the literal receiver name is
    #: recognized otherwise, so an alias would smuggle the import past the
    #: scan.
    modules: frozenset[str]


def _bound_imports(tree: ast.AST) -> _ImportBindings:
    """Collect the dynamic-import callables and ``importlib`` aliases."""
    callables: set[str] = {"__import__"}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            callables.update(
                alias.asname or alias.name for alias in node.names if alias.name == "import_module"
            )
        elif isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name for alias in node.names if alias.name == "importlib"
            )
        elif isinstance(node, ast.Assign):
            callables.update(_import_module_assignment_targets(node))
    return _ImportBindings(frozenset(callables), frozenset(modules))


def _import_module_assignment_targets(node: ast.Assign) -> list[str]:
    """Names a plain assignment binds to ``importlib.import_module`` itself:
    ``load = importlib.import_module`` aliases the callable."""
    value = node.value
    if (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "importlib"
        and value.attr == "import_module"
    ):
        return [target.id for target in node.targets if isinstance(target, ast.Name)]
    return []


def _literal_import(node: ast.Call, bindings: _ImportBindings) -> str | None:
    """The literal module name of a dynamic-import call, when it is one."""
    func = node.func
    if isinstance(func, ast.Name):
        if func.id not in bindings.callables:
            return None
    elif (
        isinstance(func, ast.Attribute)
        and func.attr == "import_module"
        and isinstance(func.value, ast.Name)
        and func.value.id in bindings.modules
    ):
        pass  # importlib.import_module through an aliased module binding
    else:
        return None
    if not node.args:
        return None
    argument = node.args[0]
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    return None


class _Scanner(ast.NodeVisitor):
    """Collects every import-shaped statement in one module."""

    def __init__(self, ctx: _ScanContext, path: Path, tree: ast.AST) -> None:
        self.ctx = ctx
        self.path = path
        self.bound = _bound_imports(tree)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.ctx.classify(alias.name, self.path, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level > 0:
            return  # relative: inside the extension's own package
        if node.module:
            self.ctx.classify(node.module, self.path, node.lineno)
            # ``from maistro_ext_sdk import _internal`` — the private seam can
            # arrive as an imported *name*; a public root's underscore names
            # are private no matter the import form.
            head = node.module.split(".")[0]
            if head in PUBLIC_SDK_ROOTS:
                for alias in node.names:
                    if alias.name.startswith("_"):
                        self.ctx.findings.append(
                            (
                                str(self.path),
                                node.lineno,
                                "private-module",
                                f"{node.module}.{alias.name}",
                                "underscore-prefixed modules are private even "
                                "under the public SDK root",
                            )
                        )

    def visit_Call(self, node: ast.Call) -> None:
        # sys.path.insert/append/extend(...): the checkout repair that makes
        # a repo-relative import work at runtime. The method set matches the
        # repository's own gate (check-extension-imports.py), which already
        # treats ``extend`` as a mutation.
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in ("insert", "append", "extend")
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "path"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "sys"
        ):
            self.ctx.findings.append(
                (
                    str(self.path),
                    node.lineno,
                    "sys-path-repair",
                    "sys.path." + func.attr,
                    "mutating sys.path repairs for a checkout layout; shipped "
                    "extensions import what their wheel ships",
                )
            )
        literal = _literal_import(node, self.bound)
        if literal is not None:
            self.ctx.classify(literal, self.path, node.lineno)
        self.generic_visit(node)


def _own_package_roots(root: Path) -> frozenset[str]:
    """The extension's own import roots: first-segment packages of the tree.

    Both shipped layouts count: the SDK's flat layout (the package at the
    root, next to ``extension.json``) and the ``src/`` layout the
    repository's reference extension uses.
    """
    own: set[str] = set()
    for candidate in root.iterdir():
        if candidate.is_dir() and ((candidate / "__init__.py").is_file()):
            own.add(candidate.name)
    src = root / "src"
    if src.is_dir():
        for candidate in src.iterdir():
            if candidate.is_dir() and ((candidate / "__init__.py").is_file()):
                own.add(candidate.name)
    return frozenset(own)


def security_checks(
    root: Path,
    *,
    entrypoint_module: str | None,
    declared: tuple[str, ...] = (),
) -> tuple[CheckRecord, ...]:
    """Run the static security checks over an extension's source tree.

    ``entrypoint_module`` comes from the (already validated) manifest; when
    it is ``None`` the manifest did not parse, and the entrypoint check
    records that as its failure rather than inventing a pass.
    """
    try:
        from importlib.metadata import packages_distributions

        dist_for_root: dict[str, list[str]] = packages_distributions()  # type: ignore[assignment]
    except Exception:  # pragma: no cover - metadata unavailable is exotic
        dist_for_root = {}

    ctx = _ScanContext(
        root=root,
        declared=frozenset(declared),
        own_packages=_own_package_roots(root),
        dist_for_root=dist_for_root,
    )

    python_files = sorted(root.rglob("*.py"))
    unparsed: list[str] = []
    for path in python_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            unparsed.append(f"{path}: {exc}")
            continue
        _Scanner(ctx, path, tree).visit(tree)

    def _record(check_id: str, description: str, rule: str) -> CheckRecord:
        hits = [f for f in ctx.findings if f[2] == rule]
        if hits:
            detail = "; ".join(f"{f[0]}:{f[1]} {f[3]} ({f[4]})" for f in hits)
            return CheckRecord(
                check_id=check_id,
                description=description,
                status=CheckStatus.FAILED,
                detail=detail,
            )
        return CheckRecord(
            check_id=check_id,
            description=description,
            status=CheckStatus.PASSED,
            detail=(f"{len(python_files)} Python file(s) scanned; no {rule} finding"),
        )

    records: list[CheckRecord] = [
        _record(
            "security/imports-public-only",
            "shipped imports resolve only to the standard library, the public "
            "SDK, the extension's own package, or declared dependencies",
            "product-private-import",
        ),
        _record(
            "security/no-undeclared-dependencies",
            "every third-party import root is declared in pyproject.toml",
            "undeclared-dependency",
        ),
        _record(
            "security/no-private-modules",
            "no underscore-prefixed (private) module is imported",
            "private-module",
        ),
        _record(
            "security/no-checkout-repair",
            "no repository-relative import (packages.*, extensions.*)",
            "repo-relative-import",
        ),
        _record(
            "security/no-sys-path-repair",
            "sys.path is not mutated to rescue imports",
            "sys-path-repair",
        ),
    ]

    if unparsed:
        records.append(
            CheckRecord(
                check_id="security/sources-parse",
                description="every shipped Python file parses",
                status=CheckStatus.FAILED,
                detail="; ".join(unparsed),
            )
        )
    else:
        records.append(
            CheckRecord(
                check_id="security/sources-parse",
                description="every shipped Python file parses",
                status=CheckStatus.PASSED,
                detail=f"{len(python_files)} Python file(s) parsed",
            )
        )

    if entrypoint_module is None:
        records.append(
            CheckRecord(
                check_id="security/entrypoint-inside-own-package",
                description="the manifest entrypoint names a module inside the "
                "extension's own package",
                status=CheckStatus.FAILED,
                detail="the manifest did not parse, so no entrypoint could be checked",
            )
        )
    else:
        head = entrypoint_module.split(".")[0]
        if head in ctx.own_packages:
            records.append(
                CheckRecord(
                    check_id="security/entrypoint-inside-own-package",
                    description="the manifest entrypoint names a module inside the "
                    "extension's own package",
                    status=CheckStatus.PASSED,
                    detail=f"{entrypoint_module!r} lives inside {head!r}",
                )
            )
        else:
            records.append(
                CheckRecord(
                    check_id="security/entrypoint-inside-own-package",
                    description="the manifest entrypoint names a module inside the "
                    "extension's own package",
                    status=CheckStatus.FAILED,
                    detail=(
                        f"entrypoint {entrypoint_module!r} names package {head!r}, "
                        f"which is not one of the extension's own packages "
                        f"{sorted(ctx.own_packages)} — a host would import that "
                        "module as extension code"
                    ),
                )
            )
    return tuple(records)
