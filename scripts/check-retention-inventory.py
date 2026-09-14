#!/usr/bin/env python3
"""Verify that every Alembic-created durable table has a retention policy."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_CREATE_TABLE = re.compile(r'op\.create_table\(\s*["\']([^"\']+)', re.MULTILINE)
_MIGRATION_TABLE_CONSTANT = re.compile(r'^\s*_TABLE\s*=\s*["\']([^"\']+)', re.MULTILINE)
_RUNTIME_CREATE = re.compile(r"CREATE TABLE IF NOT EXISTS[ \t]+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_REQUIRED_FIELDS = {
    "table",
    "data_class",
    "owner",
    "legal_security_requirement",
    "growth_rate",
    "policy",
    "action",
}


def migration_tables(root: Path) -> set[str]:
    """Return literal table names owned by migrations, not test fixtures."""
    tables: set[str] = set()
    for path in (root / "alembic" / "versions").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        tables.update(_CREATE_TABLE.findall(text))
        tables.update(_MIGRATION_TABLE_CONSTANT.findall(text))
    return tables


def runtime_tables(root: Path) -> set[str]:
    """Return table names created by shipped package runtime schemas."""
    tables: set[str] = set()
    for path in (root / "packages").glob("*/src/**/*.py"):
        tables.update(_RUNTIME_CREATE.findall(path.read_text(encoding="utf-8")))
    return tables


def inventory_tables(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = document.get("tables")
    if not isinstance(entries, list):
        raise ValueError("retention inventory must contain a tables list")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("table"), str):
            raise ValueError("every retention entry must name a table")
        name = entry["table"]
        if name in result:
            raise ValueError(f"duplicate retention entry: {name}")
        missing = _REQUIRED_FIELDS - entry.keys()
        if missing:
            raise ValueError(f"{name} is missing fields: {', '.join(sorted(missing))}")
        result[name] = entry
    return result


def check(root: Path) -> list[str]:
    path = root / "docs" / "persistence" / "retention-inventory.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        entries = inventory_tables(document)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [str(exc)]
    missing = sorted((migration_tables(root) | runtime_tables(root)) - entries.keys())
    if missing:
        return ["durable tables missing retention policy: " + ", ".join(missing)]
    if document.get("schema_version") != 1:
        return ["retention inventory schema_version must be 1"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    failures = check(args.root)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("retention inventory covers all migration and runtime durable tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
