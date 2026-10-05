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
- every `return` statement in the handler's own scope returns a literal
  composed purely of constants (`[]`, `{"status": "clean"}`, a stock
  Dockerfile) — a nested helper's returns are that helper's scope, not the
  route's, and
- the handler's executed scope contains no `Call` node except
  `HTTPException(...)`. Executed scope: a statement that only *defines* a
  nested function or lambda runs the definition — its decorators (Python
  applies a decorator the moment the def runs, so a lambda decorator's body
  executes exactly once here), its defaults, and its annotations, unless
  the module defers annotation evaluation with `from __future__ import
  annotations` (as most route modules do — those annotations are strings at
  runtime and are dropped at the parse boundary, able to justify nothing)
  — but not the nested body, which waits for an invocation the detector
  does not speculate about. A route may define helpers it never calls, so
  their calls are the helper's, not the route's (#1858). When the helper
  *is* called, the call site itself is a `Call` in this scope and counts.
  That credit is deliberately lexical, not interprocedural: the detector
  does not follow into a called helper's body, so work performed only
  there is invisible to it.

  One more deliberate limit sits in `_canned_handlers`: a handler with no
  own-scope `return` is not classified at all. Treating fallthrough as an
  implicit constant `None` would also condemn the shapes the gate exists
  to allow — generator responses (`yield`) and raise-only `HTTPException`
  refusals — so return-less handlers stay with review instead of a guessed
  control-flow rule.

The inventory
-------------
The audited routes and their dispositions live in
`quality/api-route-contracts.json`, with the human-readable contract table in
`docs/api/route-contract-inventory.md`. Every registered entry must still
resolve to a live handler (method + path matched against the decorator) whose
name equals the entry's `handler` field, so the inventory cannot rot: removing
a route means updating the inventory in the same change, and renaming a
handler means reconciling its declaration. A canned handler that is *not* registered fails the gate unless
it carries a `temporary` disposition with a tracking issue and an unexpired
review date — the same escape shape `check-public-routes.py` uses, because
"we know, it is tracked" must be writable and must expire.

Usage
-----
    python3 scripts/check-api-route-contracts.py
"""

from __future__ import annotations

import ast
import json
import sys
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = ROOT / "packages" / "hive-conductor" / "backend" / "routes"
REGISTRY = ROOT / "quality" / "api-route-contracts.json"
INVENTORY_DOC = ROOT / "docs" / "api" / "route-contract-inventory.md"

DISPOSITIONS = frozenset({"implemented", "unsupported-501", "preview", "temporary"})
REQUIRED_FIELDS = ("route", "method", "path", "file", "handler", "disposition", "contract")
REQUIRED_TEMPORARY = ("issue", "expires")
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


def _parameters(args: ast.arguments) -> list[ast.arg]:
    """Every parameter node of a signature, position-only through ``**``."""
    return [
        parameter
        for parameter in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
        if parameter is not None
    ]


def _postpones_annotations(tree: ast.Module) -> bool:
    """True when the module defers all annotation evaluation (PEP 563)."""
    return any(
        isinstance(statement, ast.ImportFrom)
        and statement.module == "__future__"
        and any(alias.name == "annotations" for alias in statement.names)
        for statement in tree.body
    )


def _drop_postponed_annotations(tree: ast.Module) -> None:
    """Model PEP 563 at the parse boundary: annotations never execute.

    Under ``from __future__ import annotations`` the compiler stores every
    annotation as a string, so a call written inside one never runs — not
    in a handler's signature and not in a nested helper's. Erasing them
    keeps the executed-scope walk from crediting work the module cannot
    perform, for every function in the file.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        node.returns = None
        for parameter in _parameters(node.args):
            parameter.annotation = None


def _definition_time_expressions(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.expr]:
    """What a ``def`` evaluates at once, before its body ever runs.

    Decorators, argument defaults and annotations execute in the enclosing
    scope the moment the def statement is reached; only the body defers to
    call time. A decorator is not merely evaluated — Python applies it,
    calling it with the function object at once — so a lambda decorator's
    body also runs here, exactly once. (Annotations of a module that
    postpones them never reach this list: `_drop_postponed_annotations`
    erases them at the parse boundary.)
    """
    args = node.args
    eager: list[ast.expr] = []
    for decorator in node.decorator_list:
        eager.append(decorator)
        if isinstance(decorator, ast.Lambda):
            eager.append(decorator.body)
    eager.extend(args.defaults)
    eager.extend(default for default in args.kw_defaults if default is not None)
    eager.extend(parameter.annotation for parameter in _parameters(args) if parameter.annotation)
    if node.returns is not None:
        eager.append(node.returns)
    return eager


def _walk_executed_scope(roots: list[ast.stmt]) -> Iterator[ast.AST]:
    """Yield every node that runs when the handler's own statements run.

    The lexical execution boundary the detector judges. A statement that
    defines a nested function executes that definition — the def-time
    expressions above — but not the nested body, which waits for an
    invocation; a lambda's body defers the same way. Everything else runs
    here and is yielded, including class bodies (a class statement executes
    its body immediately) and nested functions inside them.
    """
    stack: list[ast.AST] = list(roots)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(_definition_time_expressions(node))
        elif isinstance(node, ast.Lambda):
            stack.extend(node.args.defaults)
            stack.extend(default for default in node.args.kw_defaults if default is not None)
        else:
            stack.extend(ast.iter_child_nodes(node))


def _own_scope_returns(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """The handler's own ``return`` statements, not its nested helpers'."""
    return [node for node in _walk_executed_scope(func.body) if isinstance(node, ast.Return)]


def _performs_real_work(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the executed scope calls anything except HTTPException.

    Walks the handler's executed scope (`_walk_executed_scope`), not the
    whole function tree: the handler's own ``@router.<method>(...)``
    decorator is a Call on every decorated handler and counting it made the
    detector unable to fire, and a call inside a nested definition belongs
    to that definition, which the route may never invoke (#1858) — defining
    a writing helper is not route work. A helper the route actually calls
    justifies the route through its call site; that credit stops there
    (lexical, not interprocedural analysis).
    """
    for node in _walk_executed_scope(func.body):
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
        if _postpones_annotations(tree):
            _drop_postponed_annotations(tree)
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
) -> list[str]:
    """The handlers answering canned data without an accepted disposition.

    Only handlers with at least one own-scope `return` are classified: a
    nested helper's return belongs to the helper (#1858), and a handler
    with none of its own — generator responses (`yield`), raise-only
    `HTTPException` refusals — is left to review rather than condemned by
    an implicit-`None` rule that would sweep in those deliberate shapes.
    """
    findings: list[str] = []
    for filename, func, method, route_path in handlers:
        returns = _own_scope_returns(func)
        if not returns:
            continue
        if not all(_pure_constant(r.value) for r in returns):
            continue
        if _performs_real_work(func):
            continue
        findings.append(f"{filename}:{func.lineno} {method.upper()} {route_path} ({func.name})")
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
        func = by_identity.get(identity)
        if func is None:
            failures.append(
                f"inventory rot: {entry['method'].upper()} {entry['route']} "
                f"({entry['file']} @{entry['path']}) does not resolve to a live handler"
            )
            continue
        declared_handler = str(entry["handler"])
        if declared_handler != func.name:
            failures.append(
                f"handler identity drift: {entry['method'].upper()} {entry['route']} "
                f"({entry['file']} @{entry['path']}) declares handler {declared_handler!r} "
                f"but the live function is {func.name!r}; reconcile the inventory entry"
            )
        if disposition == "temporary":
            if not entry.get("issue"):
                failures.append(f"{entry['route']}: temporary disposition needs an issue")
            expired = _temporary_expired(entry)
            if expired:
                failures.append(f"{entry['route']}: temporary disposition {expired}")
    return failures, count


def main() -> int:
    failures: list[str] = []

    handlers = _handlers()
    by_identity = {(f, m, p): func for f, func, m, p in handlers}
    canned = _canned_handlers(handlers)

    registry_failures, registered_count = _check_registry(by_identity)
    failures.extend(registry_failures)

    for finding in canned:
        try:
            registry_name = str(REGISTRY.relative_to(ROOT))
        except ValueError:  # relocated/synthetic registry (tests, tooling)
            registry_name = str(REGISTRY)
        failures.append(
            f"canned route handler: {finding} returns only constants and performs no "
            f"operation; implement it against its canonical owner, refuse with an "
            f"explicit unsupported status, or register a temporary disposition in "
            f"{registry_name}"
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
