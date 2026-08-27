#!/usr/bin/env python3
"""Fail when a new production module becomes unreachable from every entry point.

Build a module-level import graph over production code, root it at real process
entry points, and ratchet the unreachable set against a reviewed baseline.
Reachability is a floor, not proof that an advertised capability is active.
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "reachability-baseline.json"
_FLAT_PREFIX = "@flat/"
_TOOL_PREFIX = "@tool/"

#: Repo tooling. Not production code and not on any package path, so the walk
#: above cannot see it — which is why a CI gate's acceptance criteria could
#: never reach the ladder's top rung (ADR-082526-aef8). Rooted at the workflow
#: steps that execute it rather than at a declared list: a list drifts the
#: moment a step is renamed, and the workflow file is already the authority on
#: what CI runs.
TOOLING_DIR = "scripts"
WORKFLOW_GLOB = ".github/workflows/*.yml"


@dataclass(frozen=True)
class FlatApp:
    """A standalone application whose modules resolve from a flat sys.path root."""

    name: str
    path: str
    roots: tuple[str, ...]
    dynamic_roots: tuple[str, ...] = ()
    # Hive predates scoped flat-app identities in the baseline. Keep its report
    # labels stable while using scoped keys internally; new apps get a prefix.
    report_prefix: str = ""


# Standalone production processes outside packages/*/src. Keep this explicit:
# collection validates every packages/*/backend Python tree has a declaration,
# so adding another flat backend cannot silently put it outside the analysis.
FLAT_APPS = (
    FlatApp(
        name="hive-conductor",
        path="packages/hive-conductor/backend",
        roots=("main",),
        dynamic_roots=(
            "routes.design",
            "routes.canvas",
            "routes.evolution",
            "routes.rsi",
            "services.design_service",
            "services.design_preview",
            "services.design_render",
            "services.evolution",
            "services.scheduler",
            "services.memory_decay",
            "services.dag_run_store",
        ),
    ),
    FlatApp(
        name="maistro-turing-backend",
        path="packages/maistro-turing/backend",
        roots=("main",),
        report_prefix="maistro-turing-backend",
    ),
)

# Package/module process entry points. Flat application roots live with their
# declarations above so generic names such as `main` never collide.
STATIC_ROOTS = (
    "maistro_server.main",
    "maistro.cli",
    "maistro_registry.cli",
    "maistro_rsi.cli",
    "maistro_bootstrap",
)

# Package modules reached only through runtime strings or external launchers.
DYNAMIC_ROOTS = (
    "maistro_server.entrypoint",  # Docker ENTRYPOINT: python -m maistro_server.entrypoint
    "maistro_rsi.__main__",
    "maistro_turing.runtime",
    "maistro_canvas.canvas.routes",
)


def _tool_key(name: str) -> str:
    return f"{_TOOL_PREFIX}{name}"


def _collect_tooling(root: Path) -> dict[str, Path]:
    """Every tooling script, keyed by filename stem.

    Keyed by stem rather than dotted name because these are not importable
    modules: `check-ac-state.py` is not a legal identifier, and the scripts run
    as files. The stem is what a workflow names and what a sibling import would
    use, so it is the identity both root discovery and the import walk need.
    """
    tooling = root / TOOLING_DIR
    if not tooling.is_dir():
        return {}
    return {_tool_key(path.stem): path for path in sorted(tooling.glob("*.py"))}


def _workflow_text(root: Path) -> str:
    return "\n".join(path.read_text(errors="replace") for path in sorted(root.glob(WORKFLOW_GLOB)))


def _tooling_roots(mods: dict[str, Path], workflows: str) -> set[str]:
    """Scripts a workflow step executes, found by filename in the workflow text.

    Matching on the file name is deliberately literal. A script invoked through
    a shell variable, or from a shell script the workflow calls, is not seen —
    the same blind spot `_eager_sweep` exists for on the package side, and it
    errs toward reporting a script unreachable rather than toward silence.
    """
    return {
        key for key, path in mods.items() if key.startswith(_TOOL_PREFIX) and path.name in workflows
    }


def _tooling_edges(path: Path, tooling: dict[str, Path]) -> set[str]:
    """Sibling scripts this one imports, or names as a string.

    The string half is not optional. `scripts/ac_outcome_plugin.py` is reached
    only as the literal "ac_outcome_plugin" inside `check-ac-state.py`, loaded
    as a pytest plugin and never imported. An import-only walk reports a live
    plugin as dead, which is the wrong answer in the direction this gate exists
    to get right.
    """
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return set()
    stems = {key[len(_TOOL_PREFIX) :] for key in tooling}
    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            named.add(node.module.split(".")[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            named.add(node.value)
    return {_tool_key(stem) for stem in named & stems}


def _is_production_python(path: Path, base: Path) -> bool:
    rel = path.relative_to(base)
    return "tests" not in rel.parts and not path.name.startswith("test_")


def _production_python_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return [path for path in base.rglob("*.py") if _is_production_python(path, base)]


def _validate_flat_apps(root: Path, flat_apps: tuple[FlatApp, ...]) -> None:
    declared = {app.path for app in flat_apps}
    discovered = {
        path.relative_to(root).as_posix()
        for path in root.glob("packages/*/backend")
        if _production_python_files(path)
    }
    undeclared = sorted(discovered - declared)
    missing = sorted(declared - discovered)
    if undeclared:
        raise RuntimeError(
            "standalone backend(s) are outside reachability analysis; declare them in "
            f"FLAT_APPS: {', '.join(undeclared)}"
        )
    if missing:
        raise RuntimeError(
            "declared standalone backend(s) contain no production Python modules: "
            f"{', '.join(missing)}"
        )


def _validate_no_shadowed_modules(root: Path) -> None:
    """Refuse a flat module sitting beside a package directory of the same name.

    `foo.py` next to `foo/__init__.py` is not a warning — Python resolves
    `import pkg.foo` to the package, always, so the flat file can never run.
    Two such files existed here for months carrying "DEAD CODE — superseded"
    docstrings, and this gate could not have found them: `_collect_modules` keys
    modules by dotted name, so one silently overwrote the other and only one was
    ever analysed. A module the analyser cannot see is worse than a module it
    reports as unreachable.
    """
    collisions: list[str] = []
    for base in [*root.glob("packages/*/src"), *root.glob("packages/*/backend")]:
        for directory in base.rglob("*"):
            if not directory.is_dir() or directory.name == "__pycache__":
                continue
            if not (directory / "__init__.py").exists():
                continue  # not a regular package; it cannot shadow anything
            flat = directory.parent / f"{directory.name}.py"
            if flat.exists():
                collisions.append(flat.relative_to(root).as_posix())
    if collisions:
        raise RuntimeError(
            "module(s) shadowed by a same-named package and unreachable by construction — "
            "delete the flat file or rename one of them: " + ", ".join(sorted(collisions))
        )


def _flat_key(app_name: str, module: str) -> str:
    return f"{_FLAT_PREFIX}{app_name}/{module}"


def _flat_identity(key: str) -> tuple[str, str] | None:
    if not key.startswith(_FLAT_PREFIX):
        return None
    app_name, module = key[len(_FLAT_PREFIX) :].split("/", 1)
    return app_name, module


def _collect_modules(
    root: Path = ROOT, flat_apps: tuple[FlatApp, ...] = FLAT_APPS
) -> dict[str, Path]:
    """Return scoped module identity → file for every production module."""
    _validate_flat_apps(root, flat_apps)
    _validate_no_shadowed_modules(root)
    mods: dict[str, Path] = {}

    def add_tree(base: Path, prefix: str, app_name: str | None = None) -> None:
        for path in _production_python_files(base):
            parts = list(path.relative_to(base).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            name = ".".join(([prefix] if prefix else []) + parts)
            if name:
                key = _flat_key(app_name, name) if app_name else name
                # Preserve the scanner's previous behavior for import layouts that
                # expose both x.py and x/__init__.py under one package name.
                mods[key] = path

    for src in sorted(root.glob("packages/*/src")):
        for pkg in sorted(src.iterdir()):
            if pkg.is_dir() and (pkg / "__init__.py").exists():
                add_tree(pkg, pkg.name)

    for app in flat_apps:
        add_tree(root / app.path, "", app.name)

    mods.update(_collect_tooling(root))

    return mods


def _eager_sweep(tree: ast.AST, selfmod: str) -> set[str]:
    """Sibling modules a package imports by name in an eager-import sweep.

    A node/plugin catalog registers its implementations by importing them at
    package-import time::

        module_names = ("jira_poll", "llm_summarize", ...)
        for name in module_names:
            importlib.import_module(f"{__name__}.{name}")

    Those imports are real — the modules run on every import of the package —
    but they are invisible to an AST walk that only reads `import` statements,
    so an honest catalog looked like eighteen dead modules. Recognising the
    idiom is the difference between the gate reporting dead code and reporting
    its own blind spot.

    Deliberately narrow: the loop's iterable must be a literal tuple/list of
    strings (or a name bound to one in the same scope), and the interpolation
    must be exactly ``f"{__name__}.{loop_variable}"``. Anything else is left
    unresolved rather than guessed at, because a wrong "reachable" verdict is
    the failure this gate exists to prevent.
    """
    out: set[str] = set()
    for scope in ast.walk(tree):
        if not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Module):
            continue
        literals = _string_sequences(scope)
        for loop in ast.walk(scope):
            if not isinstance(loop, ast.For) or not isinstance(loop.target, ast.Name):
                continue
            names = _sequence_strings(loop.iter, literals)
            if not names:
                continue
            if not any(_is_sibling_import(call, loop.target.id) for call in ast.walk(loop)):
                continue
            out.update(f"{selfmod}.{name}" for name in names)
    return out


def _string_sequences(scope: ast.AST) -> dict[str, tuple[str, ...]]:
    """Names bound to a literal tuple/list of strings *in this scope's own body*.

    Deliberately not an ``ast.walk``: walking would hoist every function's
    locals into the module scope, so a tuple bound in one function could resolve
    a loop in another that would ``NameError`` at run time — the recogniser
    would claim a module reachable on the strength of code that cannot run.
    A module-level binding read inside a function still resolves, because the
    module-scope pass walks down to find that loop; only the leak in the other
    direction is closed.
    """
    bound: dict[str, tuple[str, ...]] = {}
    for node in getattr(scope, "body", ()):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and (values := _literal_strings(node.value)):
            bound[target.id] = values
    return bound


def _literal_strings(node: ast.expr) -> tuple[str, ...]:
    if not isinstance(node, ast.Tuple | ast.List):
        return ()
    values = [
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]
    return tuple(values) if len(values) == len(node.elts) else ()


def _sequence_strings(node: ast.expr, bound: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return bound.get(node.id, ())
    return _literal_strings(node)


def _is_sibling_import(node: ast.AST, loop_variable: str) -> bool:
    """True for ``importlib.import_module(f"{__name__}.{loop_variable}")``."""
    if not isinstance(node, ast.Call) or len(node.args) != 1:
        return False
    callee = node.func
    name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", None)
    if name != "import_module":
        return False
    template = node.args[0]
    if not isinstance(template, ast.JoinedStr) or len(template.values) != 3:
        return False
    head, dot, tail = template.values
    return (
        isinstance(head, ast.FormattedValue)
        and isinstance(head.value, ast.Name)
        and head.value.id == "__name__"
        and isinstance(dot, ast.Constant)
        and dot.value == "."
        and isinstance(tail, ast.FormattedValue)
        and isinstance(tail.value, ast.Name)
        and tail.value.id == loop_variable
    )


def _imports(path: Path, selfmod: str) -> set[str]:
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return set()
    out: set[str] = _eager_sweep(tree, selfmod)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                own = selfmod.split(".")
                pkg = own if path.name == "__init__.py" else own[:-1]
                up = node.level - 1
                pkg = pkg[: len(pkg) - up] if up else pkg
                base = ".".join(pkg + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            out.update(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
            out.add(base)
    return out


def _resolve(name: str, mods: dict[str, Path], app_name: str | None = None) -> str | None:
    parts = name.split(".")
    while parts:
        candidate = ".".join(parts)
        # Flat imports resolve against that application's sys.path first. This
        # lets Hive and Turing both have main, routes.*, config, state, etc.
        if app_name and (flat := _flat_key(app_name, candidate)) in mods:
            return flat
        if candidate in mods:
            return candidate
        parts.pop()
    return None


def _module_import_name(key: str) -> str:
    flat = _flat_identity(key)
    return flat[1] if flat else key


def _module_app_name(key: str) -> str | None:
    flat = _flat_identity(key)
    return flat[0] if flat else None


def _ancestor_keys(key: str, mods: dict[str, Path]) -> list[str]:
    flat = _flat_identity(key)
    app_name = flat[0] if flat else None
    module = flat[1] if flat else key
    parts = module.split(".")
    ancestors: list[str] = []
    for index in range(1, len(parts)):
        name = ".".join(parts[:index])
        candidate = _flat_key(app_name, name) if app_name else name
        if candidate in mods:
            ancestors.append(candidate)
    return ancestors


def _reachability(
    root: Path = ROOT,
    flat_apps: tuple[FlatApp, ...] = FLAT_APPS,
    static_roots: tuple[str, ...] = STATIC_ROOTS,
    dynamic_roots: tuple[str, ...] = DYNAMIC_ROOTS,
) -> tuple[dict[str, Path], set[str]]:
    mods = _collect_modules(root, flat_apps)
    tooling = {key: path for key, path in mods.items() if key.startswith(_TOOL_PREFIX)}
    edges: dict[str, set[str]] = {}
    for key, path in mods.items():
        if key in tooling:
            # Tooling resolves against its own flat namespace, never against a
            # package name that happens to match a script stem.
            edges[key] = _tooling_edges(path, tooling) - {key}
            continue
        app_name = _module_app_name(key)
        import_name = _module_import_name(key)
        edges[key] = {
            resolved
            for imported in _imports(path, import_name)
            if (resolved := _resolve(imported, mods, app_name)) and resolved != key
        }

    stack = [root_name for root_name in (*static_roots, *dynamic_roots) if root_name in mods]
    stack.extend(_tooling_roots(tooling, _workflow_text(root)))
    for app in flat_apps:
        stack.extend(
            key
            for root_name in (*app.roots, *app.dynamic_roots)
            if (key := _flat_key(app.name, root_name)) in mods
        )

    seen: set[str] = set()
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        stack.extend(edges.get(module, ()))
        # Importing a.b.c executes parent __init__.py modules. Keep those parent
        # identities inside the same flat-app scope when applicable.
        stack.extend(_ancestor_keys(module, mods))

    return mods, seen


def _display_name(key: str, flat_apps: tuple[FlatApp, ...]) -> str:
    if key.startswith(_TOOL_PREFIX):
        # The repo path, not a dotted name: these are files a person opens, and
        # `scripts/mutation_ratchet.py` is findable where `mutation_ratchet` is
        # one grep away from the wrong thing.
        return f"{TOOLING_DIR}/{key[len(_TOOL_PREFIX) :]}.py"
    flat = _flat_identity(key)
    if not flat:
        return key
    app_name, module = flat
    app = next(app for app in flat_apps if app.name == app_name)
    return f"{app.report_prefix}::{module}" if app.report_prefix else module


def unreachable_modules(
    root: Path = ROOT,
    flat_apps: tuple[FlatApp, ...] = FLAT_APPS,
    static_roots: tuple[str, ...] = STATIC_ROOTS,
    dynamic_roots: tuple[str, ...] = DYNAMIC_ROOTS,
) -> tuple[list[str], int]:
    mods, seen = _reachability(root, flat_apps, static_roots, dynamic_roots)
    unreachable = sorted(_display_name(key, flat_apps) for key in set(mods) - seen)
    return unreachable, len(mods)


def main() -> int:
    unreachable, total = unreachable_modules()
    baseline = set(json.loads(BASELINE.read_text())["unreachable"])

    added = sorted(set(unreachable) - baseline)
    removed = sorted(baseline - set(unreachable))

    print(f"{total} production modules, {len(unreachable)} unreachable from any entry point")

    if removed:
        print(f"\n{len(removed)} module(s) newly REACHABLE — drop them from the baseline:")
        for module in removed:
            print(f"  - {module}")

    if added:
        print(f"\n{len(added)} module(s) are NEWLY UNREACHABLE:\n")
        for module in added:
            print(f"  {module}")
        print(
            "\nNothing that runs imports these. If that is intended — a library-only\n"
            "surface, or test scaffolding — add them to quality/reachability-baseline.json\n"
            "with a note. If it is not, they are built-but-never-wired: give them a call\n"
            "path, and check that no doc already claims they run."
        )

    if added or removed:
        if removed:
            print(
                "\nThe reviewed baseline must shrink when modules become reachable. "
                "Remove the stale entries above before merging."
            )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
