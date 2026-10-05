#!/usr/bin/env python3
"""Gate: shipped API routes must not answer with canned data (#389).

What it catches
---------------
`POST /v1/settings/reload` returned `{"status": "reloaded"}` without reloading
anything. `GET /v1/schedules/history` returned `[]` forever. `POST /v1/mcp/
discover` returned `{"tools": [], "status": "scanning"}`. Each answered 200 for
an operation that did nothing — and because `fetch` does not reject on a lie,
every one of them looked like it worked for as long as it shipped.

That is the failure mode this gate refuses at review time: a route handler
whose every `return` is a literal built only from constants (`[]`,
`{"status": "clean"}`, a stock Dockerfile) and whose body performs no call
beyond raising `HTTPException`. Such a handler cannot observe or change any
state; everything it answers is canned. Handlers that return constants but do
real work (logout clears the session, mark-all-read writes every message) are
not flagged: the constant is their acknowledgement, not their payload.

How it decides
--------------
AST over `packages/hive-conductor/backend/routes/*.py`. A handler is canned
when:

- it is decorated with `@router.<method>(...)`, and
- every `return` statement's value is a literal composed purely of constants,
  and
- the body contains no `Call` node except `HTTPException(...)`.

The inventory
-------------
The audited routes and their dispositions live in
`quality/api-route-contracts.json`, with the human-readable contract table in
`docs/api/route-contract-inventory.md`. Every registered entry must still
resolve to a live handler (method + path matched against the decorator), so
the inventory cannot rot: removing a route means updating the inventory in the
same change.

Registration is tracking, not a pass (#1859): every canned handler fails this
gate whether it is registered or not. A `temporary` disposition — a tracking
issue and an unexpired review date, validated with the same shape
`check-public-routes.py` uses because "we know, it is tracked" must be
writable and must expire — records the known debt and keeps it expiring while
the gate stays red. #389 grants no temporary waiver for a success answer that
did nothing, so the only way to ship the route is to implement it against its
canonical owner or refuse with an explicit unsupported status.

Usage
-----
    python3 scripts/check-api-route-contracts.py
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = ROOT / "packages" / "hive-conductor" / "backend" / "routes"
REGISTRY = ROOT / "quality" / "api-route-contracts.json"
INVENTORY_DOC = ROOT / "docs" / "api" / "route-contract-inventory.md"

DISPOSITIONS = frozenset({"implemented", "unsupported-501", "preview", "temporary"})
REQUIRED_FIELDS = ("route", "method", "path", "file", "handler", "disposition", "contract")
REQUIRED_TEMPORARY = ("issue", "expires")


def _pure_constant(node: ast.expr) -> bool:
    """True when the expression is built only from literals."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_pure_constant(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(_pure_constant(k) for k in node.keys if k is not None) and all(
            _pure_constant(v) for v in node.values
        )
    return False


def _performs_real_work(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the body calls anything except HTTPException construction.

    Walks the body statements, not the whole function node: the handler's own
    ``@router.<method>(...)`` decorator is a Call on every decorated handler,
    and counting it here made every handler look like it did real work — the
    detector could never fire (found by the in-process coverage tests).
    """
    for statement in func.body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                func_node = node.func
                if isinstance(func_node, ast.Name) and func_node.id == "HTTPException":
                    continue
                return True
    return False


def _router_decorator(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, str] | None:
    """The (method, path) a `@router.<method>("path")` decorator declares."""
    for dec in func.decorator_list:
        if (
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and isinstance(dec.func.value, ast.Name)
            and dec.func.value.id == "router"
            and dec.args
            and isinstance(dec.args[0], ast.Constant)
        ):
            return dec.func.attr, str(dec.args[0].value)
    return None


def _handlers() -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, str, str]]:
    """Every router handler as (file, node, method, path)."""
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, str, str]] = []
    for path in sorted(ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            declared = _router_decorator(node)
            if declared is None:
                continue
            method, route_path = declared
            found.append((path.name, node, method, route_path))
    return found


def _canned_handlers(
    handlers: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, str, str]],
) -> list[tuple[tuple[str, str, str], str]]:
    """Canned handlers as ((file, method, path), display). The identity is the
    registry key, so ``main()`` can tell a tracked entry from an unregistered
    one when it words the failure."""
    findings: list[tuple[tuple[str, str, str], str]] = []
    for filename, func, method, route_path in handlers:
        returns = [n for n in ast.walk(func) if isinstance(n, ast.Return)]
        if not returns:
            continue
        if not all(_pure_constant(r.value) for r in returns):
            continue
        if _performs_real_work(func):
            continue
        findings.append(
            (
                (filename, method, route_path),
                f"{filename}:{func.lineno} {method.upper()} {route_path} ({func.name})",
            )
        )
    return findings


def _temporary_expired(entry: dict[str, object]) -> str | None:
    raw = entry.get("expires")
    if isinstance(raw, str):
        try:
            expires = date.fromisoformat(raw)
        except ValueError:
            return f"unparseable expires {raw!r}"
        if expires < date.today():
            return f"expired {raw}"
        return None
    dt = raw if isinstance(raw, datetime) else None
    if dt is not None:
        return f"expired {dt.date().isoformat()}" if dt.date() < date.today() else None
    return "temporary disposition carries no parseable expires date"


def _check_registry(
    by_identity: dict[tuple[str, str, str], ast.FunctionDef | ast.AsyncFunctionDef],
) -> tuple[list[str], int]:
    """Validate the inventory against the live route table."""
    failures: list[str] = []
    count = 0
    if not REGISTRY.exists():
        return [f"missing registry: {REGISTRY}"], count
    registry = json.loads(REGISTRY.read_text())
    for entry in registry.get("routes", []):
        count += 1
        missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            failures.append(f"registry entry for {entry.get('route', '?')} is missing {missing}")
            continue
        disposition = str(entry["disposition"])
        if disposition not in DISPOSITIONS:
            failures.append(
                f"{entry['route']}: unknown disposition {disposition!r} "
                f"(one of {sorted(DISPOSITIONS)})"
            )
        identity = (str(entry["file"]), str(entry["method"]), str(entry["path"]))
        if by_identity.get(identity) is None:
            failures.append(
                f"inventory rot: {entry['method'].upper()} {entry['route']} "
                f"({entry['file']} @{entry['path']}) does not resolve to a live handler"
            )
            continue
        if disposition == "temporary":
            if not entry.get("issue"):
                failures.append(f"{entry['route']}: temporary disposition needs an issue")
            expired = _temporary_expired(entry)
            if expired:
                failures.append(f"{entry['route']}: temporary disposition {expired}")
    return failures, count


def _registry_routes() -> dict[tuple[str, str, str], dict[str, object]]:
    """The inventory keyed by handler identity; empty when it cannot be read
    (a missing or malformed registry is reported by ``_check_registry``)."""
    try:
        registry = json.loads(REGISTRY.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    routes = registry.get("routes") if isinstance(registry, dict) else None
    if not isinstance(routes, list):
        return {}
    keyed: dict[tuple[str, str, str], dict[str, object]] = {}
    for entry in routes:
        if not isinstance(entry, dict):
            continue
        identity = (entry.get("file"), entry.get("method"), entry.get("path"))
        if all(isinstance(part, str) for part in identity):
            keyed[(identity[0], identity[1], identity[2])] = entry
    return keyed


def main() -> int:
    failures: list[str] = []

    handlers = _handlers()
    by_identity = {(f, m, p): func for f, func, m, p in handlers}
    canned = _canned_handlers(handlers)

    registry_failures, registered_count = _check_registry(by_identity)
    failures.extend(registry_failures)

    try:
        registry_name = str(REGISTRY.relative_to(ROOT))
    except ValueError:  # relocated/synthetic registry (tests, tooling)
        registry_name = str(REGISTRY)
    registered = _registry_routes()
    for identity, finding in canned:
        entry = registered.get(identity)
        if isinstance(entry, dict) and entry.get("disposition") == "temporary":
            failures.append(
                f"canned route handler: {finding} returns only constants and performs no "
                f"operation; its temporary disposition (issue #{entry.get('issue')}, "
                f"expires {entry.get('expires', 'unspecified')}) is tracking-only and "
                f"does not pass this gate — implement it against its canonical owner "
                f"or refuse with an explicit unsupported status"
            )
        else:
            failures.append(
                f"canned route handler: {finding} returns only constants and performs no "
                f"operation; implement it against its canonical owner or refuse with an "
                f"explicit unsupported status — a temporary disposition registered in "
                f"{registry_name} records the debt for review but cannot pass this gate"
            )

    if not INVENTORY_DOC.exists():
        failures.append(f"missing inventory document: {INVENTORY_DOC}")

    if failures:
        print(f"check-api-route-contracts: {len(failures)} finding(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    canned_note = f", {len(canned)} canned" if canned else "0 canned"
    print(
        f"check-api-route-contracts: OK ({len(handlers)} handlers scanned, "
        f"{registered_count} audited routes registered, {canned_note})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
