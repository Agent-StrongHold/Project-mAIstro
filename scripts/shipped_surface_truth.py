"""Truthful shipped-surface inventory for M1 Gate D (#465)."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
#: GET is normally read-only, but these routes establish or consume
#: authentication state and therefore belong in the execution/security matrix.
_SECURITY_ROUTE_RE = re.compile(
    r"(?:oauth|oidc|openid|authorize|authentication|identity|token|login|logout|permission|elevat)",
    re.IGNORECASE,
)
#: Not an HTTP verb, so never a member of MUTATING_METHODS -- a WebSocket route
#: is a distinct kind of shipped execution/control surface (#1122) and must be
#: discovered on its own terms, not folded into the mutating-method vocabulary.
WEBSOCKET_METHOD = "WEBSOCKET"
#: Stand-in method for a registration whose `methods=` argument the gate
#: cannot read statically (`methods=MUTATING_METHODS`, a list holding a
#: name). It may well contain POST, so the route is a matrix-required
#: surface exactly like a dynamic path -- never a silently dropped one.
DYNAMIC_METHODS = "<dynamic-methods>"
VALID_DISPOSITIONS = {
    "canonical",
    "domain-state",
    "local-only",
    "disabled",
    "unresolved",
}
SUCCESS_STATUS = {
    "success",
    "succeeded",
    "complete",
    "completed",
    "done",
    "building",
    "running",
    "started",
}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "site-packages",
    "tests",
    "__tests__",
    "examples",
    "fixtures",
    "reference",
    "references",
    "dist",
    "build",
    "__pycache__",
}
_FRONTEND_STATUS_RE = re.compile(
    r"\b(?:complete|completed|success|succeeded|building|running|started|done|progress)\b",
    re.IGNORECASE,
)
_TIMER_CALLBACK_RE = re.compile(
    r"setTimeout\s*\(\s*(?:\(\s*\)\s*=>|function\s*\([^)]*\))\s*"
    r"(?P<body>\{.*?\}|.*?)(?=,\s*\d[\d_]*\s*\))",
    re.DOTALL,
)
_FETCH_RE = re.compile(
    r"fetch\s*\(\s*(?P<quote>['\"`])(?P<route>[^'\"`]+)(?P=quote)\s*,\s*\{(?P<opts>.*?)\}\s*\)",
    re.DOTALL,
)
# A shipped client commonly hoists endpoint paths into constants. Keep this
# deliberately small and literal: resolving a named string is safe, while an
# arbitrary expression must remain an explicit dynamic surface.
_JS_STRING_ASSIGNMENT_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?P<quote>['\"`])(?P<value>[^'\"`]+)(?P=quote)"
)
_JS_VARIABLE_FETCH_RE = re.compile(
    r"fetch\s*\(\s*(?P<target>[A-Za-z_$][\w$]*)\s*,\s*\{(?P<opts>.*?)\}\s*\)",
    re.DOTALL,
)
# Express and router registrations are shipped backend handlers even when the
# file lives beside a frontend bundle. They need a matrix disposition just like
# Python routes; a non-literal first argument gets a line/digest stand-in.
_JS_MUTATING_ROUTE_RE = re.compile(
    r"\b(?:app|router|api|server|[A-Za-z_$][\w$]*(?:Router|App|Server))\."
    r"(?P<method>post|put|patch|delete)\s*\(\s*(?P<target>[^,\n\r]+)",
    re.IGNORECASE,
)
_METHOD_RE = re.compile(r"\bmethod\s*:\s*['\"](?P<method>POST|PUT|PATCH|DELETE)['\"]", re.I)


@dataclass(frozen=True, order=True)
class BackendSurface:
    source: str
    method: str
    route: str
    handler: str
    obvious_fake_success: bool = False

    @property
    def key(self) -> str:
        return f"{self.source}:{self.method}:{self.route}:{self.handler}"


@dataclass(frozen=True, order=True)
class FrontendSurface:
    source: str
    signal: str
    method: str = ""
    route: str = ""

    @property
    def key(self) -> str:
        suffix = f":{self.method}:{self.route}" if self.method or self.route else ""
        return f"{self.source}:{self.signal}{suffix}"


def load_matrix(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 2:
        raise ValueError("surface matrix schema_version must be 2")
    return raw


def _excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    return (
        any(part in EXCLUDED_PARTS for part in rel.parts)
        or ".test." in path.name
        or ".spec." in path.name
    )


def _declared_methods(
    call: ast.Call,
    *,
    positional_index: int | None = None,
    include_security_get: bool = False,
) -> list[str]:
    """The mutating methods a registration's ``methods`` argument names.

    A literal collection of string literals is read; the mutating subset is
    returned. Anything else -- a name, a call, a collection holding a
    non-literal element -- cannot be proven free of ``POST``, so it yields the
    one conservative stand-in rather than nothing: the route stays in the
    fail-closed inventory and the matrix must classify it. Starlette's
    ``add_route`` also accepts ``methods`` as a third positional argument;
    callers pass that index explicitly. No ``methods=`` at all is the
    framework default GET. It is normally omitted, but a security-marked
    route opts into GET explicitly.
    """
    methods_expr: ast.expr | None = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "methods"),
        None,
    )
    if methods_expr is None and positional_index is not None and len(call.args) > positional_index:
        methods_expr = call.args[positional_index]
    if methods_expr is None:
        return ["GET"] if include_security_get else []
    if not isinstance(methods_expr, (ast.List, ast.Tuple, ast.Set)):
        return [DYNAMIC_METHODS]
    methods: list[str] = []
    for item in methods_expr.elts:
        if not (isinstance(item, ast.Constant) and isinstance(item.value, str)):
            return [DYNAMIC_METHODS]
        methods.append(item.value.upper())
    allowed = set(MUTATING_METHODS)
    if include_security_get:
        allowed.add("GET")
    return [method for method in methods if method in allowed]


def _security_surface(path: str, handler: str | None = None) -> bool:
    """Whether a GET registration can make an authentication decision."""
    return bool(_SECURITY_ROUTE_RE.search(path) or (handler and _SECURITY_ROUTE_RE.search(handler)))


def _path_argument(call: ast.Call) -> ast.expr | None:
    """The route-path expression a registration passes, positional or `path=`."""
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "path":
            return keyword.value
    return None


def _route_path(expr: ast.expr, *, dynamic_at: ast.expr) -> str:
    """The route string a registration names, literal or a stand-in for one that is not.

    A path built from an f-string, a variable, or any other non-literal
    expression cannot be read statically -- but the registration is still a
    shipped mutating/WebSocket surface (#1144), so it is never silently
    dropped from discovery. It gets a synthetic, line-stable identifier
    instead, which the matrix must explicitly classify like any other route:
    "requires an explicit reviewed dynamic-route declaration" rather than
    disappearing because the checker could not read the string.
    """
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    # The expression's digest is part of the identity, not only its line:
    # rewriting `f"{PREFIX}/safe"` to `f"{PREFIX}/admin"` on the same line is
    # a different shipped route and must not inherit the old disposition.
    digest = hashlib.sha256(ast.unparse(expr).encode("utf-8")).hexdigest()[:8]
    return f"<dynamic-route:{dynamic_at.lineno}:{digest}>"


def _decorated_routes(node: ast.AsyncFunctionDef | ast.FunctionDef) -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        path_expr = _path_argument(decorator)
        if path_expr is None:
            continue
        path = _route_path(path_expr, dynamic_at=decorator)
        name = decorator.func.attr.lower()
        security_get = _security_surface(path, node.name)
        methods = [name.upper()] if name.upper() in MUTATING_METHODS else []
        if name == "get" and security_get:
            methods = ["GET"]
        elif name in {"api_route", "route"}:
            methods = _declared_methods(decorator, include_security_get=security_get)
        elif name == "websocket":
            # Every WebSocket route is a shipped execution/control surface
            # regardless of "mutating": it bypasses HTTP-method semantics
            # entirely and, per this repo's own `AuthMiddleware`, bypasses
            # ordinary HTTP middleware too (#1122).
            methods = [WEBSOCKET_METHOD]
        routes.extend((method, path) for method in methods)
    return routes


def _call_attr_name(call: ast.Call) -> str | None:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else None


def _handler_identity(expr: ast.expr) -> tuple[str | None, bool]:
    """`(identity, resolvable)` for a call-registered route's endpoint.

    A bare name is the handler's identity and may be correlated to a
    function defined in this module. A qualified endpoint (`handlers.build`)
    keeps its qualifier as identity and is never resolved by its bare
    attribute name: this module may define an unrelated `build` whose canned
    return would then be attributed to the imported real handler. Anything
    else (a call, a subscript) has no static identity at all.
    """
    if isinstance(expr, ast.Name):
        return expr.id, True
    if isinstance(expr, ast.Attribute):
        return ast.unparse(expr), False
    return None, False


#: Placeholder handler identity for a resolvable route whose endpoint
#: argument is not a plain name/attribute this gate can read statically.
#: Still a real, matrix-required entry (#1144) -- only body inspection for an
#: obvious fake-success no-op is unavailable for it.
_UNRESOLVED_ENDPOINT = "<unresolved endpoint>"


def _registered_route_calls(tree: ast.Module) -> list[tuple[str, str, str | None, bool]]:
    """Discover call-registered FastAPI and Starlette routes.

    ``add_api_route`` and ``add_route`` have no decorator for
    ``_decorated_routes`` to see. Starlette's ``add_route`` accepts its
    methods collection positionally (or by keyword), so that form must be
    retained rather than silently treated as a default GET.
    """
    found: list[tuple[str, str, str | None, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        registration = _call_attr_name(node)
        if registration not in {"add_api_route", "add_route", "add_websocket_route"}:
            continue
        path_expr = _path_argument(node)
        if path_expr is None:
            continue
        path = _route_path(path_expr, dynamic_at=node)
        endpoint = node.args[1] if len(node.args) >= 2 else None
        for keyword in node.keywords:
            if keyword.arg == "endpoint":
                endpoint = keyword.value
        handler, resolvable = _handler_identity(endpoint) if endpoint is not None else (None, False)
        if registration == "add_websocket_route":
            methods = [WEBSOCKET_METHOD]
        else:
            methods = _declared_methods(
                node,
                positional_index=2 if registration == "add_route" else None,
                include_security_get=_security_surface(path, handler),
            )
        found.extend((method, path, handler, resolvable) for method in methods)
    return found


class _OwnReturns(ast.NodeVisitor):
    """Every `return` statement in one function's own body, not a nested scope.

    A `return` belonging to a closure/helper defined *inside* the handler is
    not the handler's own return path and must not be attributed to it, so
    this stops descending at any nested function/lambda/class boundary.
    """

    def __init__(self) -> None:
        self.returns: list[ast.Return] = []

    def visit_Return(self, node: ast.Return) -> None:
        self.returns.append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass


def _literal_success_status(value: ast.expr | None) -> str | None:
    if not isinstance(value, ast.Dict):
        return None
    for key, item in zip(value.keys, value.values, strict=True):
        if not isinstance(key, ast.Constant) or key.value != "status":
            continue
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            return item.value.lower()
    return None


#: Call names this gate accepts as observability rather than real work, when
#: used as their own statement (`log(...)`, `logger.info(...)`). Anything
#: else -- a service call, a database write, a background-task scheduler --
#: means the handler is not a no-op, however its final `return` reads.
_LOG_LIKE_CALL_NAMES = {"log", "logger", "logging", "metrics", "print"}
#: ``object()`` is a deliberately inert local placeholder, not an execution
#: effect. Keep this exception narrow: arbitrary calls assigned to locals may
#: perform the work that makes a status response truthful.
_INERT_CALL_NAMES = {"object"}


def _call_root_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        base = func.value
        return base.id if isinstance(base, ast.Name) else None
    if isinstance(func, ast.Name):
        return func.id
    return None


class _RealWorkDetector(ast.NodeVisitor):
    """Whether a handler's own body does anything beyond logging/metrics and
    a canned literal return, stopping at nested function/lambda/class scopes.

    `await`, `try`, and `with`/`async with` are each independently strong
    evidence that real work happens: real I/O, a call worth guarding against
    failure, or a resource being held. Any call other than a bare
    logging/metrics statement is treated the same way -- this gate does not
    try to prove a given call is inert, only to recognize the narrow shape
    that is obviously not.
    """

    def __init__(self) -> None:
        self.has_real_work = False

    def visit_Await(self, node: ast.Await) -> None:
        self.has_real_work = True

    def visit_Try(self, node: ast.Try) -> None:
        self.has_real_work = True

    def visit_With(self, node: ast.With) -> None:
        self.has_real_work = True

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.has_real_work = True

    def visit_Call(self, node: ast.Call) -> None:
        root = _call_root_name(node)
        inert_builtin = (
            isinstance(node.func, ast.Name)
            and node.func.id in _INERT_CALL_NAMES
            and not node.args
            and not node.keywords
        )
        if not inert_builtin and (root is None or root.lower() not in _LOG_LIKE_CALL_NAMES):
            self.has_real_work = True
        self.generic_visit(node)

    # A write through an attribute or a subscript (`record.status = "done"`,
    # `state["enabled"] = True`, `del jobs[job_id]`) mutates something that
    # outlives the handler, so it is real work whatever the return says. A
    # plain local name binding is inert and stays permitted.
    def visit_Assign(self, node: ast.Assign) -> None:
        self._note_targets(node.targets)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._note_targets([node.target])
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._note_targets([node.target])
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        self._note_targets(node.targets)
        self.generic_visit(node)

    def _note_targets(self, targets: list[ast.expr]) -> None:
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, (ast.Attribute, ast.Subscript)):
                    self.has_real_work = True
                    return

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass


def _does_real_work(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    detector = _RealWorkDetector()
    for statement in node.body:
        detector.visit(statement)
        if detector.has_real_work:
            return True
    return False


def _returned_status(node: ast.AsyncFunctionDef | ast.FunctionDef) -> str | None:
    """The literal `status` every reachable return in this handler agrees on,
    for a handler whose own body does no real work beyond that return.

    Deliberately conservative, but over the *whole* body rather than one
    statement: flags a handler only when every one of its own return
    statements -- found anywhere in it, through ordinary control flow,
    regardless of what non-branching logging/metrics/assignment statements
    precede them -- is the identical literal success-shaped dict, *and*
    nothing else in the body does real work (#1144). A handler that awaits a
    real effect, guards one with `try`/`with`, or calls anything beyond
    logging is not "obvious" no matter how its return reads; it must be
    classified from evidence in the matrix, not guessed here.
    """
    if _does_real_work(node):
        return None
    collector = _OwnReturns()
    for statement in node.body:
        collector.visit(statement)
    if not collector.returns:
        return None
    statuses = {_literal_success_status(ret.value) for ret in collector.returns}
    if len(statuses) != 1:
        return None
    (status,) = statuses
    return status


def _obvious_fake(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    status = _returned_status(node)
    return status in SUCCESS_STATUS if status is not None else False


def _function_nodes(tree: ast.Module) -> list[ast.AsyncFunctionDef | ast.FunctionDef]:
    """Every function definition in this module, in source order, duplicates kept.

    Decorator discovery walks *these*, never a by-name map: Python happily
    registers `@router.post("/a")` and then redefines the same function name
    for `@router.post("/b")`, both routes stay live at runtime, and a map
    keyed on the name would report only the later one.
    """
    return [
        node for node in ast.walk(tree) if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    ]


def _function_defs(
    nodes: list[ast.AsyncFunctionDef | ast.FunctionDef],
) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    """Best-effort by-name map for resolving a call-registered handler.

    Only `router.add_api_route("/x", handler, ...)` uses it, and only to
    inspect a *candidate* handler's obvious-fake-success shape -- never to
    decide whether a route exists. When more than one function shares a
    name across nested scopes, the last one encountered wins.
    """
    return {node.name: node for node in nodes}


def _source_surfaces(path: Path, repo_root: Path) -> list[BackendSurface]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    source = path.relative_to(repo_root).as_posix()
    surfaces: list[BackendSurface] = []
    nodes = _function_nodes(tree)
    functions = _function_defs(nodes)
    for node in nodes:
        obvious_fake = _obvious_fake(node)
        for method, route in _decorated_routes(node):
            surfaces.append(
                BackendSurface(
                    source=source,
                    method=method,
                    route=route,
                    handler=node.name,
                    obvious_fake_success=obvious_fake,
                )
            )
    for method, route, handler_name, resolvable in _registered_route_calls(tree):
        handler_def = functions.get(handler_name) if handler_name and resolvable else None
        surfaces.append(
            BackendSurface(
                source=source,
                method=method,
                route=route,
                handler=handler_name or _UNRESOLVED_ENDPOINT,
                obvious_fake_success=_obvious_fake(handler_def) if handler_def else False,
            )
        )
    return surfaces


def _iter_source_files(
    repo_root: Path, roots: Iterable[str], suffixes: tuple[str, ...]
) -> Iterable[Path]:
    for root_name in roots:
        root = repo_root / root_name
        if not root.is_dir():
            raise ValueError(f"surface root does not exist: {root_name}")
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes or _excluded(path, root):
                continue
            yield path


def discover_backend_surfaces(repo_root: Path, roots: list[str]) -> list[BackendSurface]:
    surfaces: list[BackendSurface] = []
    for path in _iter_source_files(repo_root, roots, (".py",)):
        surfaces.extend(_source_surfaces(path, repo_root))
    return sorted(set(surfaces))


def _timer_success_signal(text: str) -> bool:
    for match in _TIMER_CALLBACK_RE.finditer(text):
        if _FRONTEND_STATUS_RE.search(match.group("body")):
            return True
    return False


def _js_string_bindings(text: str) -> dict[str, str]:
    return {
        match.group("name"): match.group("value")
        for match in _JS_STRING_ASSIGNMENT_RE.finditer(text)
    }


def _js_route_path(target: str, *, bindings: dict[str, str], line: int) -> str:
    target = target.strip()
    if len(target) >= 2 and target[0] in "'\"`" and target[-1] == target[0]:
        return target[1:-1]
    if re.fullmatch(r"[A-Za-z_$][\w$]*", target) and target in bindings:
        return bindings[target]
    digest = hashlib.sha256(target.encode("utf-8")).hexdigest()[:8]
    return f"<dynamic-route:{line}:{digest}>"


def _js_fetch_method(options: str) -> str | None:
    literal = _METHOD_RE.search(options)
    if literal:
        return literal.group("method").upper()
    # An unreadable method may contain POST; retain the call rather than
    # silently treating it as a read-only/default-GET request.
    if re.search(r"\bmethod\s*:", options):
        return DYNAMIC_METHODS
    return None


def _mutating_fetches(text: str) -> set[tuple[str, str]]:
    bindings = _js_string_bindings(text)
    found: set[tuple[str, str]] = set()
    for match in _FETCH_RE.finditer(text):
        method = _js_fetch_method(match.group("opts"))
        if method:
            found.add((method, match.group("route")))
    for match in _JS_VARIABLE_FETCH_RE.finditer(text):
        method = _js_fetch_method(match.group("opts"))
        route = bindings.get(match.group("target"))
        if route is None:
            route = _js_route_path(
                match.group("target"),
                bindings=bindings,
                line=text.count("\n", 0, match.start()) + 1,
            )
        if method:
            found.add((method, route))
    return found


def _mutating_js_routes(text: str) -> set[tuple[str, str]]:
    bindings = _js_string_bindings(text)
    found: set[tuple[str, str]] = set()
    for match in _JS_MUTATING_ROUTE_RE.finditer(text):
        route = _js_route_path(
            match.group("target"),
            bindings=bindings,
            line=text.count("\n", 0, match.start()) + 1,
        )
        found.add((match.group("method").upper(), route))
    return found


def discover_frontend_surfaces(repo_root: Path, roots: list[str]) -> list[FrontendSurface]:
    surfaces: list[FrontendSurface] = []
    for path in _iter_source_files(repo_root, roots, (".ts", ".tsx", ".js", ".jsx")):
        text = path.read_text(encoding="utf-8")
        source = path.relative_to(repo_root).as_posix()
        if _timer_success_signal(text):
            surfaces.append(FrontendSurface(source=source, signal="timer-status-simulation"))
        for method, route in _mutating_fetches(text):
            surfaces.append(
                FrontendSurface(
                    source=source,
                    signal="mutating-api-call",
                    method=method,
                    route=route,
                )
            )
        for method, route in _mutating_js_routes(text):
            surfaces.append(
                FrontendSurface(
                    source=source,
                    signal="mutating-api-route",
                    method=method,
                    route=route,
                )
            )
    return sorted(set(surfaces))


# Backward-compatible name used by the abandoned branch's tests/imports.
discover_frontend_signals = discover_frontend_surfaces


def _backend_entry_key(entry: dict[str, Any]) -> str:
    return ":".join(
        (
            str(entry.get("source", "")),
            str(entry.get("method", "")),
            str(entry.get("route", "")),
            str(entry.get("handler", "")),
        )
    )


def _frontend_entry_key(entry: dict[str, Any]) -> str:
    suffix = (
        f":{entry.get('method', '')}:{entry.get('route', '')}"
        if entry.get("method") or entry.get("route")
        else ""
    )
    return f"{entry.get('source', '')}:{entry.get('signal', '')}{suffix}"


def _nonblank_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_entry(entry: dict[str, Any], *, strict: bool) -> list[str]:
    errors: list[str] = []
    disposition = entry.get("disposition")
    if disposition not in VALID_DISPOSITIONS:
        return [f"invalid disposition {disposition!r}"]
    if not isinstance(entry.get("production_enabled"), bool):
        errors.append("production_enabled must be true or false")
    if not _nonblank_string(entry.get("reason")):
        errors.append("missing reason")
    if disposition in {"canonical", "domain-state"} and not _nonblank_string(
        entry.get("effect_owner")
    ):
        errors.append(f"{disposition} surface must name effect_owner")
    if disposition == "local-only" and not _nonblank_string(entry.get("truth_contract")):
        errors.append("local-only surface must name truth_contract")
    if disposition in {"disabled", "unresolved"} and not isinstance(entry.get("owner_issue"), int):
        errors.append(f"{disposition} surface must name owner_issue")
    if disposition == "disabled" and entry.get("production_enabled") is True:
        errors.append("disabled surface cannot be production_enabled")
    if strict and disposition == "unresolved" and entry.get("production_enabled") is True:
        errors.append("production-enabled unresolved surface blocks Gate D")
    return errors


def _index_entries(
    entries: list[dict[str, Any]], key_fn: Any, label: str
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    indexed: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for entry in entries:
        key = key_fn(entry)
        if key in indexed:
            errors.append(f"duplicate {label} entry: {key}")
        indexed[key] = entry
    return indexed, errors


def _coverage_errors(
    discovered_keys: set[str],
    entry_keys: set[str],
    *,
    unclassified_label: str,
    stale_label: str,
) -> list[str]:
    errors = [f"{unclassified_label}: {key}" for key in sorted(discovered_keys - entry_keys)]
    errors.extend(f"{stale_label}: {key}" for key in sorted(entry_keys - discovered_keys))
    return errors


def _backend_entry_errors(
    discovered: dict[str, BackendSurface],
    entries: dict[str, dict[str, Any]],
    *,
    strict: bool,
) -> list[str]:
    errors: list[str] = []
    for key, entry in sorted(entries.items()):
        errors.extend(f"{key}: {error}" for error in _validate_entry(entry, strict=strict))
        surface = discovered.get(key)
        if (
            surface
            and surface.obvious_fake_success
            and entry.get("production_enabled") is True
            and entry.get("disposition") not in {"disabled", "unresolved"}
        ):
            errors.append(
                f"{key}: production success-shaped no-op cannot be {entry.get('disposition')}"
            )
    return errors


def _frontend_entry_errors(
    repo_root: Path,
    entries: dict[str, dict[str, Any]],
    *,
    strict: bool,
) -> list[str]:
    errors: list[str] = []
    for key, entry in sorted(entries.items()):
        errors.extend(f"{key}: {error}" for error in _validate_entry(entry, strict=strict))
        source = repo_root / str(entry.get("source", ""))
        if not source.is_file():
            errors.append(f"{key}: frontend source does not exist")
        if (
            entry.get("signal") == "timer-status-simulation"
            and entry.get("production_enabled") is True
            and entry.get("disposition") not in {"disabled", "unresolved"}
        ):
            errors.append(
                f"{key}: production timer-driven execution state cannot be {entry.get('disposition')}"
            )
    return errors


def _product_status_errors(
    repo_root: Path,
    checks: list[dict[str, Any]],
    backend_entries: dict[str, dict[str, Any]],
) -> list[str]:
    """Keep selected product-status prose tied to a reviewed matrix entry."""
    errors: list[str] = []
    for check in checks:
        surface = str(check.get("surface", ""))
        if surface not in backend_entries:
            errors.append(f"product status check references unknown surface: {surface}")
            continue
        status_file = repo_root / str(check.get("file", ""))
        marker = check.get("contains")
        if not status_file.is_file():
            errors.append(f"product status file does not exist: {status_file}")
        elif not isinstance(marker, str) or marker not in status_file.read_text(encoding="utf-8"):
            errors.append(f"product status claim missing from {status_file}: {marker!r}")
    return errors


def validate_matrix(repo_root: Path, matrix: dict[str, Any], *, strict: bool = False) -> list[str]:
    backend = discover_backend_surfaces(repo_root, list(matrix.get("backend_roots", [])))
    frontend = discover_frontend_surfaces(repo_root, list(matrix.get("frontend_roots", [])))
    backend_entries, duplicate_backend = _index_entries(
        list(matrix.get("backend_surfaces", [])), _backend_entry_key, "backend"
    )
    frontend_entries, duplicate_frontend = _index_entries(
        list(matrix.get("frontend_surfaces", [])), _frontend_entry_key, "frontend"
    )
    discovered_backend = {surface.key: surface for surface in backend}
    discovered_frontend = {surface.key: surface for surface in frontend}
    auto_frontend_entries = {
        key: entry
        for key, entry in frontend_entries.items()
        if entry.get("signal")
        in {
            "timer-status-simulation",
            "mutating-api-call",
            "mutating-api-route",
        }
    }

    errors = [*duplicate_backend, *duplicate_frontend]
    errors.extend(
        _product_status_errors(
            repo_root,
            list(matrix.get("product_status_checks", [])),
            backend_entries,
        )
    )
    errors.extend(
        _coverage_errors(
            set(discovered_backend),
            set(backend_entries),
            unclassified_label="unclassified backend surface",
            stale_label="stale backend surface entry",
        )
    )
    errors.extend(
        _coverage_errors(
            set(discovered_frontend),
            set(auto_frontend_entries),
            unclassified_label="unclassified frontend execution surface",
            stale_label="stale frontend execution surface",
        )
    )
    errors.extend(_backend_entry_errors(discovered_backend, backend_entries, strict=strict))
    errors.extend(_frontend_entry_errors(repo_root, frontend_entries, strict=strict))
    return errors


def discovered_inventory(
    repo_root: Path, matrix: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Machine-readable current discovery, useful for review and inventory refresh."""
    return {
        "backend_surfaces": [
            surface.__dict__
            for surface in discover_backend_surfaces(
                repo_root, list(matrix.get("backend_roots", []))
            )
        ],
        "frontend_surfaces": [
            surface.__dict__
            for surface in discover_frontend_surfaces(
                repo_root, list(matrix.get("frontend_roots", []))
            )
        ],
    }


def format_errors(errors: list[str]) -> str:
    if not errors:
        return "Shipped-surface truth matrix is complete."
    return "Shipped-surface truth matrix failed:\n" + "\n".join(f"  - {error}" for error in errors)
