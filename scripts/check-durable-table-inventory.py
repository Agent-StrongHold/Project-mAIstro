#!/usr/bin/env python3
"""Every durable table has a declared retention, checked against the schema (#325).

`security_violations` was created by migration 005, appended to on every Warden
strike, and read back in full on every lock check -- and nothing anywhere
deleted from it. `usage_events` had the same shape. Neither was a decision: no
one had ever been asked how long the rows should live, so the answer defaulted
to "forever" by omission. The same was true of roughly sixty tables, because a
new `op.create_table` or `CREATE TABLE IF NOT EXISTS` had nowhere it was
required to say what happens to its rows.

`quality/durable-table-retention.json` is that place. This gate holds it to the
tree:

* every table the repository creates -- an Alembic `op.create_table`, a raw
  `CREATE TABLE` in runtime DDL, or an ORM `__tablename__` -- has an entry;
* every entry still names a table something creates, so the inventory cannot
  quietly describe a schema that no longer exists;
* every `deletion_path` imports and is callable, so a claimed purge at least
  names a real function (whether production drives it is the entry's claim,
  reviewed by people, not verified here);
* `security_violations` and `usage_events`, the two tables the issue names,
  can never drop out of it.

A table with no driven deletion path is recorded as `undecided` against the
issue tracking it. That is not a pass for the table -- it is the honest answer,
written down where the next person can find it, instead of an absence nobody
sees.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = Path("quality/durable-table-retention.json")

MIGRATION_GLOBS = (
    "alembic/versions/*.py",
    "packages/*/frontend/alembic/versions/*.py",
)
RUNTIME_DDL_GLOBS = (
    "packages/*/src/**/*.py",
    "packages/*/backend/**/*.py",
    "packages/*/frontend/server/**/*.py",
)
ORM_GLOBS = ("packages/**/*.py",)

EXCLUDED_PARTS = frozenset({"tests", "node_modules", ".venv", "__pycache__"})

REQUIRED_TABLES = ("security_violations", "usage_events")

RETENTIONS = frozenset(
    {
        "run_purge",
        "ttl_purge",
        "window_prune",
        "bounded_by_parent",
        "indefinite_by_decision",
        "undecided",
    }
)
#: Retentions that are a claim a sweep actually deletes rows, so they must name it.
DRIVEN_RETENTIONS = frozenset({"run_purge", "ttl_purge", "window_prune"})

DATA_CLASSES = frozenset(
    {
        "security_evidence",
        "audit",
        "accounting",
        "execution_state",
        "event_history",
        "conversation_history",
        "memory",
        "configuration",
        "user_content",
        "customer_pii",
        "runtime_state",
    }
)
BACKENDS = frozenset({"postgres", "sqlite"})
REQUIRED_KEYS = (
    "table",
    "backends",
    "owner_module",
    "data_class",
    "retention",
    "deletion_path",
    "issue",
)

_CREATE_TABLE = re.compile(
    r"\bCREATE\s+(?:GLOBAL\s+|LOCAL\s+)?(?P<temp>TEMP(?:ORARY)?\s+)?(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:\"?[A-Za-z_]\w*\"?\.)?\"?(?P<name>[A-Za-z_]\w*)\"?",
    re.IGNORECASE,
)
_ISSUE = re.compile(r"^#\d+$")


@dataclass(frozen=True)
class Found:
    table: str
    where: str


@dataclass
class Report:
    discovered: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    return any(part in EXCLUDED_PARTS for part in rel.parts) or rel.name.startswith("test_")


def _files(root: Path, globs: Iterable[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if path in seen or not path.is_file() or _is_excluded(path, root):
                continue
            seen.add(path)
            yield path


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, so `op.create_table(_TABLE)` resolves."""
    names: dict[str, str] = {}
    for node in tree.body:
        value: ast.expr | None = None
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            value, targets = node.value, node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value, targets = node.value, [node.target]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for target in targets:
                if isinstance(target, ast.Name):
                    names[target.id] = value.value
    return names


def ddl_tables(source: str, *, path: str = "<string>") -> list[Found]:
    """Tables a raw `CREATE TABLE` in a string literal (not a docstring) creates."""
    tree = ast.parse(source, filename=path)
    docstrings = _docstring_nodes(tree)
    found: list[Found] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings:
            continue
        for match in _CREATE_TABLE.finditer(node.value):
            name = match.group("name")
            if match.group("temp") or name.upper() == "IF":
                continue
            found.append(Found(name, f"{path}:{node.lineno}"))
    return found


def migration_tables(source: str, *, path: str = "<string>") -> list[Found]:
    """Tables an Alembic revision creates with `op.create_table`, in any layout."""
    tree = ast.parse(source, filename=path)
    constants = _module_strings(tree)
    found: list[Found] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_table"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
        ):
            continue
        keyword = next((k.value for k in node.keywords if k.arg == "table_name"), None)
        first = node.args[0] if node.args else keyword
        name: str | None = None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            name = first.value
        elif isinstance(first, ast.Name):
            name = constants.get(first.id)
        if name is None:
            raise ValueError(
                f"{path}:{node.lineno}: op.create_table with a table name this gate "
                "cannot resolve; use a literal or a module-level string constant"
            )
        found.append(Found(name, f"{path}:{node.lineno}"))
    return found + ddl_tables(source, path=path)


def orm_tables(source: str, *, path: str = "<string>") -> list[Found]:
    """Tables an ORM model declares with a class-level `__tablename__ = "..."`."""
    tree = ast.parse(source, filename=path)
    found: list[Found] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in stmt.targets)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                found.append(Found(stmt.value.value, f"{path}:{stmt.lineno}"))
    return found


def discover(root: Path) -> dict[str, list[str]]:
    """Every table the tree creates, mapped to where each creation is."""
    tables: dict[str, list[str]] = {}

    def add(items: Iterable[Found]) -> None:
        for item in items:
            tables.setdefault(item.table, []).append(item.where)

    for path in _files(root, MIGRATION_GLOBS):
        add(migration_tables(path.read_text(), path=str(path.relative_to(root))))
    for path in _files(root, RUNTIME_DDL_GLOBS):
        add(ddl_tables(path.read_text(), path=str(path.relative_to(root))))
    for path in _files(root, ORM_GLOBS):
        text = path.read_text()
        if "__tablename__" in text:
            add(orm_tables(text, path=str(path.relative_to(root))))
    return {name: sorted(set(where)) for name, where in sorted(tables.items())}


def resolve(dotted: str) -> object:
    """Import `package.module:Qual.name` and return the object it names."""
    module_name, sep, qualname = dotted.partition(":")
    if not sep or not module_name or not qualname:
        raise ValueError(f"{dotted!r} is not of the form 'module:qualname'")
    obj: object = importlib.import_module(module_name)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def _field_errors(entry: dict[str, object], root: Path, label: str) -> list[str]:
    errors: list[str] = []
    backends = entry["backends"]
    if not isinstance(backends, list) or not backends or not set(backends) <= BACKENDS:
        errors.append(f"{label}: backends must be a non-empty subset of {sorted(BACKENDS)}")
    if not (root / str(entry["owner_module"])).is_file():
        errors.append(f"{label}: owner_module {entry['owner_module']!r} is not a file in the repo")
    if entry["data_class"] not in DATA_CLASSES:
        errors.append(
            f"{label}: data_class {entry['data_class']!r} is not one of {sorted(DATA_CLASSES)}"
        )
    if entry["retention"] not in RETENTIONS:
        errors.append(
            f"{label}: retention {entry['retention']!r} is not one of {sorted(RETENTIONS)}"
        )
    policy_ref = entry.get("policy_ref")
    if policy_ref is not None and not (root / str(policy_ref)).is_file():
        errors.append(f"{label}: policy_ref {policy_ref!r} is not a file in the repo")
    return errors


def _policy_errors(entry: dict[str, object], label: str) -> list[str]:
    errors: list[str] = []
    retention, issue = entry["retention"], entry["issue"]
    if issue is not None and not (isinstance(issue, str) and _ISSUE.match(issue)):
        errors.append(f"{label}: issue must be '#<number>' or null")
    if retention == "undecided" and issue is None:
        errors.append(f"{label}: an undecided retention must name the issue tracking the decision")
    parent = entry.get("parent")
    if parent is not None and not isinstance(parent, str):
        errors.append(f"{label}: parent must be a table name")
    if retention == "bounded_by_parent" and not parent:
        errors.append(f"{label}: bounded_by_parent must name its parent table")
    deletion_path = entry["deletion_path"]
    if deletion_path is None:
        if retention in DRIVEN_RETENTIONS:
            errors.append(
                f"{label}: retention {retention!r} claims a purge but names no deletion_path"
            )
        return errors
    try:
        target = resolve(str(deletion_path))
    except Exception as exc:
        errors.append(f"{label}: deletion_path {deletion_path!r} does not resolve ({exc})")
    else:
        if not callable(target):
            errors.append(f"{label}: deletion_path {deletion_path!r} is not callable")
    return errors


def _check_entry(entry: object, root: Path, index: int) -> tuple[str | None, list[str]]:
    if not isinstance(entry, dict):
        return None, [f"entry {index}: not an object"]
    raw_table = entry.get("table")
    table = raw_table if isinstance(raw_table, str) else None
    label = repr(table) if table is not None else f"entry {index}"
    missing = [key for key in REQUIRED_KEYS if key not in entry]
    if missing:
        return table, [f"{label}: missing keys {', '.join(missing)}"]
    return table, _field_errors(entry, root, label) + _policy_errors(entry, label)


def _importable_sources(root: Path) -> None:
    """Resolve deletion paths against this tree's sources, installed or not."""
    for src in sorted(root.glob("packages/*/src")):
        if str(src) not in sys.path:
            sys.path.append(str(src))


def _declared(entries: list[object], root: Path, errors: list[str]) -> dict[str, dict[str, object]]:
    declared: dict[str, dict[str, object]] = {}
    for index, entry in enumerate(entries):
        table, entry_errors = _check_entry(entry, root, index)
        errors.extend(entry_errors)
        if table is None or not isinstance(entry, dict):
            continue
        if table in declared:
            errors.append(f"{table!r}: declared more than once")
        declared[table] = entry
    return declared


def _coverage_errors(
    discovered: dict[str, list[str]], declared: dict[str, dict[str, object]]
) -> list[str]:
    errors = [
        f"{table!r}: created at {', '.join(where)} but has no retention entry in {INVENTORY}"
        for table, where in discovered.items()
        if table not in declared
    ]
    errors += [
        f"{table!r}: in {INVENTORY} but nothing in the tree creates it (stale entry)"
        for table in declared
        if table not in discovered
    ]
    errors += [
        f"{table!r}: parent {entry['parent']!r} has no entry of its own"
        for table, entry in declared.items()
        if isinstance(entry.get("parent"), str) and entry["parent"] not in declared
    ]
    errors += [
        f"{table!r}: must stay in {INVENTORY} (named by #325)"
        for table in REQUIRED_TABLES
        if table not in declared
    ]
    return errors


def check(root: Path, inventory: object) -> Report:
    _importable_sources(root)
    try:
        report = Report(discovered=discover(root))
    except (SyntaxError, ValueError) as exc:
        return Report(errors=[f"table discovery failed: {exc}"])
    entries = inventory.get("tables") if isinstance(inventory, dict) else None
    if not isinstance(entries, list):
        report.errors.append(f"{INVENTORY}: expected an object with a 'tables' list")
        return report
    declared = _declared(entries, root, report.errors)
    report.errors.extend(_coverage_errors(report.discovered, declared))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--inventory", type=Path, default=None)
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    inventory_path: Path = args.inventory or root / INVENTORY
    report = check(root, json.loads(inventory_path.read_text()))
    if report.ok:
        print(f"ok: {len(report.discovered)} durable tables, each with a declared retention")
        return 0
    for error in report.errors:
        print(f"error: {error}", file=sys.stderr)
    print(f"\n{len(report.errors)} durable-table retention problem(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
