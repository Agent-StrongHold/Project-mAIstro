#!/usr/bin/env python3
"""Gate the Conductor surfaces the Workspace cutover retires (#1046, cutover S0.1).

`quality/workspace-retirement.json` lists every legacy page, router and
`stores.py` store with a disposition and a delete-by milestone
(docs/architecture/WORKSPACE-CUTOVER-PLAN.md, section 5). This check holds the
ledger to three rules:

* every entry is well formed (kind, disposition, owner, delete-by);
* a live entry's asset exists, and an entry marked ``deleted`` no longer does;
* nothing outside the retiring entries starts importing one: each entry
  names its current outside importers, a new one fails, and one that stops
  importing must be pruned, so the list only shrinks.

Tests are not importers: they go with the module they exercise.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypeGuard

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "quality" / "workspace-retirement.json"
CONDUCTOR = Path("packages") / "hive-conductor"
BACKEND = CONDUCTOR / "backend"
FRONTEND_SRC = CONDUCTOR / "frontend" / "src"

KINDS = frozenset({"page", "router", "store"})
DISPOSITIONS = frozenset({"PROJECT", "RETIRE", "MERGE", "KEEP"})
REQUIRED = ("kind", "path", "disposition", "replaced_by", "delete_by", "owner")
_OWNER = re.compile(r"^#\d+$")
_ROUTE_STRING = re.compile(r"^routes\.\w+$")
_SKIP_PARTS = frozenset({"tests", "__tests__", "node_modules", "__pycache__", "dist"})
_TS_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|^\s*import\s+)["']([^"']+)["']""", re.M)


def validate_entry(entry: Any, index: int) -> list[str]:
    where = f"entry {index}"
    if not isinstance(entry, dict):
        return [f"{where}: must be an object"]
    where = f"entry {index} ({entry.get('path', '?')})"
    errors = [f"{where}: missing {field!r}" for field in REQUIRED if field not in entry]
    if errors:
        return errors
    return _identity_errors(entry, where) + _lifecycle_errors(entry, where)


def _identity_errors(entry: dict[str, Any], where: str) -> list[str]:
    errors: list[str] = []
    if entry["kind"] not in KINDS:
        errors.append(f"{where}: kind {entry['kind']!r} not in {sorted(KINDS)}")
    if entry["disposition"] not in DISPOSITIONS:
        errors.append(
            f"{where}: disposition {entry['disposition']!r} not in {sorted(DISPOSITIONS)}"
        )
    if not isinstance(entry["path"], str) or not entry["path"]:
        errors.append(f"{where}: path must be a non-empty string")
    elif entry["kind"] == "store" and "::" not in entry["path"]:
        errors.append(f"{where}: a store path is '<stores.py path>::<name>'")
    if not isinstance(entry["owner"], str) or not _OWNER.match(entry["owner"]):
        errors.append(f"{where}: owner must be an issue reference like '#1046'")
    return errors


def _lifecycle_errors(entry: dict[str, Any], where: str) -> list[str]:
    errors: list[str] = []
    if entry["replaced_by"] is not None and not isinstance(entry["replaced_by"], str):
        errors.append(f"{where}: replaced_by must be a string or null")
    delete_by = entry["delete_by"]
    if entry["disposition"] == "KEEP":
        if delete_by is not None:
            errors.append(f"{where}: a KEEP entry has no delete_by (use null)")
    elif not isinstance(delete_by, str) or not delete_by:
        errors.append(f"{where}: a {entry['disposition']} entry needs a delete_by milestone")
    importers = entry.get("importers", [])
    if not isinstance(importers, list) or not all(isinstance(i, str) for i in importers):
        errors.append(f"{where}: importers must be a list of repo-relative paths")
    if not isinstance(entry.get("deleted", False), bool):
        errors.append(f"{where}: deleted must be a boolean")
    return errors


def _is_test(path: Path) -> bool:
    name = path.name
    return (
        bool(_SKIP_PARTS.intersection(path.parts))
        or name.startswith("test_")
        or name == "conftest.py"
        or ".test." in name
        or ".spec." in name
    )


def _sources(root: Path, base: Path, suffixes: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    for suffix in suffixes:
        for path in (root / base).rglob(f"*{suffix}"):
            rel = path.relative_to(root)
            if not _is_test(rel):
                found.append(rel)
    return sorted(found)


def _store_names(root: Path, stores_path: str) -> set[str]:
    path = root / stores_path
    if not path.exists():
        return set()
    names: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def asset_exists(entry: dict[str, Any], root: Path) -> bool:
    path = str(entry["path"])
    if entry["kind"] == "store":
        stores_path, name = path.split("::", 1)
        return name in _store_names(root, stores_path)
    return (root / path).exists()


def _from_import_modules(node: ast.ImportFrom, *, in_routes: bool) -> set[str]:
    """``routes.x`` modules a ``from ... import`` names, absolute or package-relative."""
    names = {a.name for a in node.names}
    if node.level == 1 and in_routes:
        return {f"routes.{node.module}"} if node.module else {f"routes.{n}" for n in names}
    if node.level != 0 or not node.module:
        return set()
    if node.module == "routes":
        return {f"routes.{n}" for n in names}
    return {node.module} if node.module.startswith("routes.") else set()


def _is_stores_attribute(node: ast.AST) -> TypeGuard[ast.Attribute]:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "stores"
    )


def _python_refs(rel: Path, tree: ast.AST) -> tuple[set[str], set[str]]:
    """Router modules (``routes.x``) and store names (``stores.x``) one file references."""
    in_routes = rel.parent == BACKEND / "routes"
    modules: set[str] = set()
    stores: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names if a.name.startswith("routes."))
        elif isinstance(node, ast.ImportFrom):
            modules |= _from_import_modules(node, in_routes=in_routes)
            if node.level == 0 and node.module == "stores":
                stores.update(a.name for a in node.names)
        elif _is_stores_attribute(node):
            stores.add(node.attr)
        elif isinstance(node, ast.Constant) and _ROUTE_STRING.match(str(node.value)):
            modules.add(str(node.value))
    return {m.split(".")[1] for m in modules}, stores


def _ts_refs(rel: Path, source: str) -> set[str]:
    refs: set[str] = set()
    for spec in _TS_IMPORT.findall(source):
        if spec.startswith("."):
            target = os.path.normpath(os.path.join(rel.parent.as_posix(), spec))
            refs.add(re.sub(r"\.(tsx?|jsx?)$", "", target))
    return refs


def find_importers(entries: list[dict[str, Any]], root: Path) -> dict[str, set[str]]:
    """Outside importers of each non-KEEP entry, keyed by entry path.

    A KEEP file outlives the cutover, so it counts as outside: it may not gain
    a consumer of a retiring asset either.
    """
    tracked = [e for e in entries if e["disposition"] != "KEEP"]
    ledger_files = {e["path"].split("::", 1)[0] for e in tracked}
    result: dict[str, set[str]] = {e["path"]: set() for e in tracked}

    routers = {Path(e["path"]).stem: e["path"] for e in tracked if e["kind"] == "router"}
    stores = {e["path"].split("::", 1)[1]: e["path"] for e in tracked if e["kind"] == "store"}
    for rel in _sources(root, CONDUCTOR, (".py",)):
        if rel.as_posix() in ledger_files:
            continue
        try:
            tree = ast.parse((root / rel).read_text(errors="replace"))
        except SyntaxError:
            continue
        modules, names = _python_refs(rel, tree)
        for module in modules & routers.keys():
            result[routers[module]].add(rel.as_posix())
        for name in names & stores.keys():
            result[stores[name]].add(rel.as_posix())

    pages = {e["path"].rsplit(".", 1)[0]: e["path"] for e in tracked if e["kind"] == "page"}
    for rel in _sources(root, FRONTEND_SRC, (".ts", ".tsx")):
        if rel.as_posix() in ledger_files:
            continue
        for ref in _ts_refs(rel, (root / rel).read_text(errors="replace")) & pages.keys():
            result[pages[ref]].add(rel.as_posix())
    return result


def check(ledger: Any, root: Path) -> list[str]:
    if not isinstance(ledger, dict) or not isinstance(ledger.get("entries"), list):
        return ["ledger must be an object with an 'entries' list"]
    entries = ledger["entries"]
    failures = [e for i, entry in enumerate(entries) for e in validate_entry(entry, i)]
    if failures:
        return failures

    seen: set[str] = set()
    for entry in entries:
        path = entry["path"]
        if path in seen:
            failures.append(f"{path}: listed twice")
        seen.add(path)
        exists = asset_exists(entry, root)
        if entry.get("deleted", False) and exists:
            failures.append(f"{path}: marked deleted but still present")
        elif not entry.get("deleted", False) and not exists:
            failures.append(f"{path}: not found; delete the entry's asset and mark it deleted")

    for path, found in find_importers(entries, root).items():
        entry = next(e for e in entries if e["path"] == path)
        allowed = set(entry.get("importers", []))
        failures.extend(
            f"{path}: NEW importer {importer} -- a retiring surface may not gain consumers"
            for importer in sorted(found - allowed)
        )
        failures.extend(
            f"{path}: {importer} no longer imports it; prune it from importers"
            for importer in sorted(allowed - found)
        )
    return failures


def main() -> int:
    if not LEDGER.exists():
        print(f"FAIL: {LEDGER} is missing", file=sys.stderr)
        return 1
    ledger = json.loads(LEDGER.read_text())
    failures = check(ledger, ROOT)
    if failures:
        print("FAIL: the workspace retirement ledger does not match the tree\n")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"OK: {len(ledger['entries'])} retirement ledger entries match the tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
