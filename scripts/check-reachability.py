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
            "routes.canvas",
            "routes.pm_fleet_v2",
            "routes.evolution",
            "routes.rsi",
            "routes.daily_report_v2",
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
    "maistro_rsi.__main__",
    "maistro_turing.runtime",
    "maistro_canvas.canvas.routes",
)


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

    return mods


def _imports(path: Path, selfmod: str) -> set[str]:
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return set()
    out: set[str] = set()
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
    edges: dict[str, set[str]] = {}
    for key, path in mods.items():
        app_name = _module_app_name(key)
        import_name = _module_import_name(key)
        edges[key] = {
            resolved
            for imported in _imports(path, import_name)
            if (resolved := _resolve(imported, mods, app_name)) and resolved != key
        }

    stack = [root_name for root_name in (*static_roots, *dynamic_roots) if root_name in mods]
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

    print("\nReachability baseline matches the current unreachable set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
