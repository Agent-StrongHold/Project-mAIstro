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
  `HTTPException(...)` and logging/metrics statements.

Executed scope: a statement that only *defines* a nested function or lambda
runs the definition — its decorators, defaults and annotations — but not its
body, which waits for an invocation the detector does not speculate about. A
route may define helpers it never calls, so their calls are the helper's, not
the route's (#1858). When the helper *is* called, the call site itself is a
`Call` in this scope and counts. That credit is deliberately lexical, not
interprocedural: the detector does not follow into a called helper's body, so
work performed only there is invisible to it.

Logging and metrics do not make a literal acknowledgement truthful (#1857): a
route that only logs and answers `{"status": "ok"}` still answered success for
an operation that did nothing, so observability calls are not real-work
evidence. What counts as observability is name-matching only — see the
limitations below.

The observability vocabulary and its limits
-------------------------------------------
This is syntactic evidence, not semantic verification of arbitrary calls.
A call is treated as observability exactly when its target is rooted in a
plain name whose lowercased form is one of `log`, `logger`, `logging`,
`metrics`, `print` — the same vocabulary the shipped-surface gate applies
to the same judgment (#1144, `shipped_surface_truth._LOG_LIKE_CALL_NAMES`;
an equality test in `tests/test_check_api_route_contracts.py` fails if the
two definitions ever diverge). The gate cannot prove that any other call is
meaningful: a call rooted outside the vocabulary makes the handler "real
work" and the constant return an acknowledgement rather than a payload —
which is the valid shape (`store.flush(); return {"status": "ok"}`), but it
is classified by name shape, not by proving the call did anything. The
mirror risk is bounded the same way: a call rooted in a variable *named*
`logger` that actually performs I/O would be misread as observability, and
attribute-rooted targets (`self.log.info(...)`, anything without a plain
name root) are deliberately never exempted. Handlers whose canned shape
hides behind non-decorator registration forms or non-literal returns are
separate, known detector leaves (#1144 owns the shipped-surface detector
class); uncalled nested definitions are judged here, by executed scope
(#1858).

The inventory
-------------
The audited routes and their dispositions live in
`quality/api-route-contracts.json`, with the human-readable contract table in
`docs/api/route-contract-inventory.md`. Every registered entry must still
resolve to a live handler (method + path matched against the decorator) whose
name equals the entry's `handler` field, so the inventory cannot rot: removing
a route means updating the inventory in the same change, and renaming a
handler means reconciling its declaration. A canned handler fails the gate unless its registry entry excuses
it with a `temporary` disposition carrying a tracking issue and an unexpired
review date — the same escape shape `check-public-routes.py` uses, because
"we know, it is tracked" must be writable and must expire. The excuse is
keyed to the entry's (file, method, path) identity and must still be valid:
a missing issue or an expired date fails the registry check and leaves the
canned finding standing, including for logging-only handlers.

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


#: Calls this gate accepts as observability rather than real work, when their
#: target is rooted in one of these plain names (`log(...)`, `logger.info(...)`).
#: A route that only logs (or reports metrics) and returns a literal still
#: answers success for an operation that did nothing, so observability cannot
#: justify the acknowledgement (#1857). The vocabulary is #1144's
#: `shipped_surface_truth._LOG_LIKE_CALL_NAMES`, mirrored rather than imported
#: because these gates are standalone scripts, not a package; an equality test
#: in `tests/test_check_api_route_contracts.py` fails if the two diverge.
_LOG_LIKE_CALL_NAMES = {"log", "logger", "logging", "metrics", "print"}


def _call_root_name(call: ast.Call) -> str | None:
    """The plain name a call's target is rooted in, mirroring #1144's
    ``shipped_surface_truth._call_root_name``: the base of an attribute chain
    only when that base is a name (`logger` in `logger.info(...)`); a bare
    name names itself; anything else has no root and is never observability."""
    func = call.func
    if isinstance(func, ast.Attribute):
        base = func.value
        return base.id if isinstance(base, ast.Name) else None
    if isinstance(func, ast.Name):
        return func.id
    return None


def _definition_time_expressions(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.expr]:
    """What a ``def`` evaluates at once, before its body ever runs.

    Decorators, argument defaults and annotations execute in the enclosing
    scope the moment the def statement is reached; only the body defers to
    call time.
    """
    args = node.args
    parameters = [
        parameter
        for parameter in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
        if parameter is not None
    ]
    eager: list[ast.expr] = [*node.decorator_list, *args.defaults]
    eager.extend(default for default in args.kw_defaults if default is not None)
    eager.extend(parameter.annotation for parameter in parameters if parameter.annotation)
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
    """True when the executed scope calls anything beyond HTTPException
    construction and logging/metrics statements.

    Walks the handler's executed scope (`_walk_executed_scope`), not the
    whole function tree: the handler's own ``@router.<method>(...)``
    decorator is a Call on every decorated handler and counting it made the
    detector unable to fire, and a call inside a nested definition belongs
    to that definition, which the route may never invoke (#1858) — defining
    a writing helper is not route work. A helper the route actually calls
    justifies the route through its call site; that credit stops there
    (lexical, not interprocedural analysis).

    Observability calls are exempt (#1857): their root name (case-insensitive)
    is in ``_LOG_LIKE_CALL_NAMES``. Everything else — a service call, a store
    write, a background-task scheduler — is real-work evidence however the
    ``return`` reads; the gate does not try to prove such a call meaningful,
    only to recognize the narrow shape that is obviously not.
    """
    for node in _walk_executed_scope(func.body):
        if isinstance(node, ast.Call):
            func_node = node.func
            if isinstance(func_node, ast.Name) and func_node.id == "HTTPException":
                continue
            root = _call_root_name(node)
            if root is not None and root.lower() in _LOG_LIKE_CALL_NAMES:
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
    exempt: frozenset[tuple[str, str, str]] = frozenset(),
) -> list[str]:
    """Canned findings, skipping identities already excused by a valid
    ``temporary`` disposition (``_temporary_exempt_identities``): the escape
    hatch must apply to logging-only handlers too, since an observability-only
    body is exactly the shape a temporary disposition exists to excuse."""
    findings: list[str] = []
    for filename, func, method, route_path in handlers:
        if (filename, method, route_path) in exempt:
            continue
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


def _temporary_exempt_identities() -> frozenset[tuple[str, str, str]]:
    """Registry identities whose `temporary` disposition is currently valid:
    a tracking issue and an unexpired review date. `main()` filters these out
    of the canned findings so the documented escape hatch holds for every
    detected handler class (#1857). A missing registry yields nothing here;
    `_check_registry` reports that failure on its own."""
    if not REGISTRY.exists():
        return frozenset()
    registry = json.loads(REGISTRY.read_text())
    exempt: set[tuple[str, str, str]] = set()
    for entry in registry.get("routes", []):
        if (
            entry.get("disposition") == "temporary"
            and entry.get("issue")
            and _temporary_expired(entry) is None
        ):
            exempt.add((str(entry["file"]), str(entry["method"]), str(entry["path"])))
    return frozenset(exempt)


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
    canned = _canned_handlers(handlers, _temporary_exempt_identities())

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
