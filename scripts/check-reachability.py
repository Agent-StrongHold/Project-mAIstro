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

# Explicit package-local developer utilities. Everything else under packages/
# that is production-shaped Python must belong to either a packaged src root or
# a declared flat application. This is intentionally tiny and reviewed: an
# ignored directory would recreate the source-universe blind spot this gate is
# meant to prevent.
_EXCLUDED_PACKAGE_PYTHON = frozenset(
    {
        "packages/hive-conductor/run_hill_climb.py",
    }
)


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


# Standalone production processes outside packages/*/src. Keep their runtime
# roots explicit, but validate coverage against every production-shaped Python
# file under packages/ rather than assuming all standalone apps are named
# `backend`. That makes a new `frontend/server`, worker, or other shipped tree
# fail closed until it is deliberately classified here.
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
    FlatApp(
        name="maistro-canvas-frontend-server",
        path="packages/maistro-canvas/frontend/server",
        roots=("lulu.service",),
        report_prefix="maistro-canvas-frontend-server",
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


def _all_package_python_files(root: Path) -> set[Path]:
    """Every production-shaped Python source file under packages/.

    This is the source-universe guard. It is deliberately independent of the
    package/flat-app declarations that the graph later uses, so a new directory
    layout cannot disappear merely because collection forgot to glob it.
    """
    packages = root / "packages"
    if not packages.exists():
        return set()
    files: set[Path] = set()
    for path in packages.rglob("*.py"):
        rel = path.relative_to(root)
        if "tests" in rel.parts or path.name.startswith("test_"):
            continue
        if rel.as_posix() in _EXCLUDED_PACKAGE_PYTHON:
            continue
        files.add(path)
    return files


def _declared_source_files(root: Path, flat_apps: tuple[FlatApp, ...]) -> set[Path]:
    covered: set[Path] = set()
    for src in sorted(root.glob("packages/*/src")):
        covered.update(_production_python_files(src))
    for app in flat_apps:
        covered.update(_production_python_files(root / app.path))
    return covered


def _validate_flat_apps(root: Path, flat_apps: tuple[FlatApp, ...]) -> None:
    declared = {app.path for app in flat_apps}
    missing = sorted(
        path for path in declared if not _production_python_files(root / path)
    )
    if missing:
        raise RuntimeError(
            "declared standalone Python tree(s) contain no production modules: "
            f"{', '.join(missing)}"
        )

    uncovered = sorted(
        path.relative_to(root).as_posix()
        for path in _all_package_python_files(root) - _declared_source_files(root, flat_apps)
    )
    if uncovered:
        raise RuntimeError(
            "production Python source is outside reachability analysis; cover it with a "
            "packaged src root, declare its standalone application root in FLAT_APPS, or "
            "record a reviewed developer-utility exclusion: " + ", ".join(uncovered)
        )


def _validate_no_shadowed_modules(
    root: Path, flat_apps: tuple[FlatApp, ...] = FLAT_APPS
) -> None:
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
    bases = [*root.glob("packages/*/src"), *(root / app.path for app in flat_apps)]
    for base in bases:
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
    _validate_no_shadowed_modules(root, flat_apps)
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
    """The scoped identities nothing imports, and the size of the module universe.

    Identities, not report labels. The baseline this feeds is read by other
    gates — `check_ac_state_impl.py` decides a criterion's `reachable` rung by
    looking its `ac-modules` anchor up in it, and that anchor is required to be
    spelled the way `_collect_modules` spells it. Reporting one spelling while
    storing another let a criterion anchored to a module that *is* baselined
    unreachable clear the top rung anyway, because the two sides never used the
    same names (#651). `display_name` makes the label a person reads, at the
    edge that prints it.
    """
    mods, seen = _reachability(root, flat_apps, static_roots, dynamic_roots)
    return sorted(set(mods) - seen), len(mods)


def display_name(key: str, flat_apps: tuple[FlatApp, ...] = FLAT_APPS) -> str:
    """The human-facing label for a scoped module identity."""
    return _display_name(key, flat_apps)


def unknown_baseline_entries(
    baseline: set[str], universe: set[str], flat_apps: tuple[FlatApp, ...] = FLAT_APPS
) -> list[tuple[str, str]]:
    """Baseline entries naming no module identity, each with a suggestion.

    A baseline the graph cannot resolve is not a stricter baseline, it is a
    hole: the entry matches nothing the walk produces, so the ratchet can never
    retire it, and every consumer that asks the baseline about a module gets
    "not listed" for one that is genuinely unreachable. The suggestion is the
    identity whose report label the entry was written as — the way all forty
    original strays arose — when exactly one identity carries that label.
    """
    labels: dict[str, list[str]] = {}
    for key in universe:
        labels.setdefault(_display_name(key, flat_apps), []).append(key)
    return [
        (entry, labels[entry][0] if len(labels.get(entry, ())) == 1 else "")
        for entry in sorted(baseline - universe)
    ]


def _report_unknown_entries(unknown: list[tuple[str, str]]) -> None:
    print(f"\n{len(unknown)} baseline entry(ies) name NO module the graph knows:\n")
    for entry, suggestion in unknown:
        # Two different faults, and they take opposite fixes. An entry that is
        # some module's *report label* is a live module written the wrong way,
        # and respelling it keeps the ratchet's grip. An entry matching nothing
        # at all is a phantom -- the module was deleted or never existed -- and
        # respelling it is impossible; it has to go.
        print(
            f"  {entry}"
            + (f"  → rename to {suggestion!r}" if suggestion else "  (no such module — delete it)")
        )
    print(
        "\nAn entry the walk cannot resolve never matches and never retires, and every\n"
        "gate that asks this baseline about a module reads 'not listed' for one that is\n"
        "genuinely unreachable. Spell entries as the identity `_collect_modules` produces:\n"
        "dotted for packages (`maistro.builders.runtime`), scoped for flat apps and repo\n"
        "tooling (`@flat/hive-conductor/routes.projects`, `@tool/ac_state_notes`)."
    )


def main() -> int:
    mods, seen = _reachability(ROOT, FLAT_APPS, STATIC_ROOTS, DYNAMIC_ROOTS)
    unreachable = sorted(set(mods) - seen)
    total = len(mods)
    baseline = set(json.loads(BASELINE.read_text())["unreachable"])

    unknown = unknown_baseline_entries(baseline, set(mods))
    added = sorted(set(unreachable) - baseline)
    # An unknown entry is already reported as unresolvable; calling it "newly
    # reachable" as well would name one fault twice and send the reader to the
    # wrong fix — pruning an entry that needs respelling.
    removed = sorted(baseline - set(unreachable) - {entry for entry, _ in unknown})

    print(f"{total} production modules, {len(unreachable)} unreachable from any entry point")

    if unknown:
        _report_unknown_entries(unknown)

    if removed:
        print(f"\n{len(removed)} module(s) newly REACHABLE — drop them from the baseline:")
        for module in removed:
            print(f"  - {display_name(module)}")

    if added:
        print(f"\n{len(added)} module(s) are NEWLY UNREACHABLE:\n")
        for module in added:
            print(f"  {display_name(module)}  ({module})")
        print(
            "\nNothing that runs imports these. If that is intended — a library-only\n"
            "surface, or test scaffolding — add them to quality/reachability-baseline.json\n"
            "with a note, spelled as the identity in parentheses. If it is not, they are\n"
            "built-but-never-wired: give them a call path, and check that no doc already\n"
            "claims they run."
        )

    if added or removed or unknown:
        if removed:
            print(
                "\nThe reviewed baseline must shrink when modules become reachable. "
                "Remove the stale entries above before merging."
            )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
