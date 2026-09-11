"""Truthful shipped-surface inventory for M1 Gate D (#465)."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
#: Not an HTTP verb, so never a member of MUTATING_METHODS -- a WebSocket route
#: is a distinct kind of shipped execution/control surface (#1122) and must be
#: discovered on its own terms, not folded into the mutating-method vocabulary.
WEBSOCKET_METHOD = "WEBSOCKET"
VALID_DISPOSITIONS = {
    "canonical",
    "domain-state",
    "local-only",
    "disabled",
    "unresolved",
}
SUCCESS_STATUS = {
    "ok",
    "success",
    "succeeded",
    "complete",
    "completed",
    "done",
    "building",
    "running",
    "started",
}
DYNAMIC_ROUTE = "<dynamic>"
UNRESOLVED_METHOD = "UNRESOLVED"
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
    r"\b(?P<callee>fetch|request|apiRequest|httpRequest)\s*\(\s*"
    r"(?P<quote>['\"`])(?P<route>[^'\"`]+)(?P=quote)\s*,\s*\{(?P<opts>.*?)\}\s*\)",
    re.DOTALL,
)
_CLIENT_METHOD_RE = re.compile(
    # A statically visible mutating method on a client/helper object is an
    # execution surface even when the object is named gateway or transport.
    r"\b(?P<client>api|apiClient|client|gateway|http|httpClient)\s*\.\s*"
    r"(?P<method>POST|PUT|PATCH|DELETE)\s*\(\s*"
    r"(?P<quote>['\"`])(?P<route>[^'\"`]+)(?P=quote)",
    re.I,
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


def _static_value(  # noqa: C901
    node: ast.AST, bindings: dict[str, ast.AST], resolving: set[str] | None = None
) -> Any:
    """Evaluate the small constant subset used by route declarations.

    This intentionally does not execute application code.  A declaration that
    falls outside this subset becomes an explicit dynamic inventory item rather
    than disappearing from the gate.
    """
    resolving = set() if resolving is None else resolving
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in bindings and node.id not in resolving:
        return _static_value(
            node=bindings[node.id], bindings=bindings, resolving={*resolving, node.id}
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_value(node.left, bindings, resolving)
        right = _static_value(node.right, bindings, resolving)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        return None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if isinstance(value, ast.FormattedValue):
                resolved = _static_value(value.value, bindings, resolving)
                if not isinstance(resolved, str):
                    return None
                parts.append(resolved)
                continue
            return None
        return "".join(parts)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: list[Any] = []
        for item in node.elts:
            if isinstance(item, ast.Starred):
                expanded = _static_value(item.value, bindings, resolving)
                if not isinstance(expanded, (list, tuple, set)):
                    return None
                values.extend(expanded)
                continue
            resolved = _static_value(item, bindings, resolving)
            if not isinstance(resolved, str):
                return None
            values.append(resolved)
        return values
    return None


def _module_bindings(tree: ast.Module) -> dict[str, ast.AST]:
    bindings: dict[str, ast.AST] = {}
    for statement in tree.body:
        targets: list[ast.expr] = []
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets = [statement.target]
            value = statement.value
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings[target.id] = value
    return bindings


def _static_string(node: ast.AST, bindings: dict[str, ast.AST]) -> str | None:
    value = _static_value(node, bindings)
    return value if isinstance(value, str) else None


def _static_methods(
    call: ast.Call, bindings: dict[str, ast.AST], *, positional_index: int | None = None
) -> list[str] | None:
    methods_node: ast.AST | None = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "methods"), None
    )
    if methods_node is None and positional_index is not None and len(call.args) > positional_index:
        methods_node = call.args[positional_index]
    if methods_node is None:
        return []
    value = _static_value(methods_node, bindings)
    if not isinstance(value, list):
        return None
    return [method.upper() for method in value if method.upper() in MUTATING_METHODS]


def _literal_methods(call: ast.Call) -> list[str]:
    """Keep the old helper useful for callers while accepting constants too."""
    return _static_methods(call, {}) or []


def _module_aliases(  # noqa: C901
    tree: ast.Module, bindings: dict[str, ast.AST]
) -> dict[str, str]:
    raw_aliases: dict[str, ast.AST] = {}
    for statement in tree.body:
        targets: list[ast.expr] = []
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets = [statement.target]
            value = statement.value
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                raw_aliases[target.id] = value

    def resolve(name: str, resolving: set[str] | None = None) -> str | None:
        resolving = set() if resolving is None else resolving
        if name in resolving or name not in raw_aliases:
            return None
        return resolve_expression(raw_aliases[name], {*resolving, name})

    def resolve_expression(node: ast.AST, resolving: set[str]) -> str | None:
        if isinstance(node, ast.Attribute):
            return node.attr.lower()
        if isinstance(node, ast.Name):
            return resolve(node.id, resolving)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
        ):
            static_name = _static_string(node.args[1], bindings)
            return static_name.lower() if static_name is not None else UNRESOLVED_METHOD
        return None

    return {name: resolved for name in raw_aliases if (resolved := resolve(name)) is not None}


def _route_decorator_name(
    decorator: ast.expr, aliases: dict[str, str], bindings: dict[str, ast.AST]
) -> str | None:
    if isinstance(decorator, ast.Attribute):
        return decorator.attr.lower()
    if isinstance(decorator, ast.Name):
        return aliases.get(decorator.id)
    if (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Name)
        and decorator.func.id == "getattr"
        and len(decorator.args) >= 2
    ):
        static_name = _static_string(decorator.args[1], bindings)
        return static_name.lower() if static_name is not None else UNRESOLVED_METHOD
    return None


def _decorated_routes(
    node: ast.AsyncFunctionDef | ast.FunctionDef,
    bindings: dict[str, ast.AST] | None = None,
    aliases: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    bindings = {} if bindings is None else bindings
    aliases = {} if aliases is None else aliases
    routes: list[tuple[str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = _route_decorator_name(decorator.func, aliases, bindings)
        if name not in {
            "post",
            "put",
            "patch",
            "delete",
            "api_route",
            "route",
            "websocket",
            "websocket_route",
            UNRESOLVED_METHOD,
        }:
            continue
        path_node = (
            decorator.args[0]
            if decorator.args
            else next(
                (keyword.value for keyword in decorator.keywords if keyword.arg == "path"), None
            )
        )
        path = _static_string(path_node, bindings) if path_node is not None else None
        route = path if path is not None else DYNAMIC_ROUTE
        if name in {"websocket", "websocket_route"}:
            methods = [WEBSOCKET_METHOD]
        elif name in {"api_route", "route"}:
            declared = _static_methods(decorator, bindings)
            # FastAPI and Starlette default these decorators to GET. An
            # unresolved methods value must remain visible because it may
            # contain a mutating verb.
            methods = [UNRESOLVED_METHOD] if declared is None else declared
        elif name == UNRESOLVED_METHOD:
            # A dynamic router method may be mutating; retain it as an owned
            # declaration instead of silently dropping the decorated handler.
            methods = [UNRESOLVED_METHOD]
        else:
            methods = [name.upper()]
        routes.extend((method, route) for method in methods)
    return routes


def _registration_endpoint_node(call: ast.Call) -> ast.AST | None:
    endpoint: ast.AST | None = call.args[1] if len(call.args) >= 2 else None
    for keyword in call.keywords:
        if keyword.arg == "endpoint":
            endpoint = keyword.value
            break
    return endpoint


def _registration_endpoint(call: ast.Call) -> str:
    endpoint = _registration_endpoint_node(call)
    if isinstance(endpoint, ast.Name):
        return endpoint.id
    if isinstance(endpoint, ast.Attribute):
        return endpoint.attr
    if isinstance(endpoint, ast.Lambda):
        return "<lambda>"
    return "<dynamic>"


def _registration_name(
    func: ast.expr, bindings: dict[str, ast.AST], aliases: dict[str, str]
) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr.lower()
    if isinstance(func, ast.Name):
        return aliases.get(func.id, "")
    if (
        isinstance(func, ast.Call)
        and isinstance(func.func, ast.Name)
        and func.func.id == "getattr"
        and len(func.args) >= 2
    ):
        static_name = _static_string(func.args[1], bindings)
        return static_name.lower() if static_name is not None else UNRESOLVED_METHOD
    return ""


def _registered_routes(
    call: ast.Call, bindings: dict[str, ast.AST], aliases: dict[str, str] | None = None
) -> list[tuple[str, str, str]]:
    aliases = {} if aliases is None else aliases
    name = _registration_name(call.func, bindings, aliases)
    if name not in {
        "add_api_route",
        "add_route",
        "add_api_websocket_route",
        "add_websocket_route",
        UNRESOLVED_METHOD,
    }:
        return []
    if name == UNRESOLVED_METHOD and not (
        len(call.args) >= 2
        or any(keyword.arg in {"endpoint", "methods"} for keyword in call.keywords)
    ):
        # A dynamic router method used as a decorator has only its path
        # argument; it is handled by _decorated_routes instead.
        return []
    path_node = (
        call.args[0]
        if call.args
        else next(
            (keyword.value for keyword in call.keywords if keyword.arg in {"path", "route"}), None
        )
    )
    route = _static_string(path_node, bindings) if path_node is not None else None
    route = route if route is not None else DYNAMIC_ROUTE
    handler = _registration_endpoint(call)
    if name in {"add_api_websocket_route", "add_websocket_route"}:
        return [(WEBSOCKET_METHOD, route, handler)]
    if name == UNRESOLVED_METHOD:
        return [(UNRESOLVED_METHOD, route, handler)]
    declared = _static_methods(
        call,
        bindings,
        # Starlette's add_route(path, endpoint, methods) accepts methods as
        # the third positional argument; keyword methods is handled for both
        # Starlette and FastAPI registrations.
        positional_index=2 if name == "add_route" else None,
    )
    # Both FastAPI and Starlette default a route registration without methods
    # to GET. An unresolved methods expression is fail-closed instead.
    methods = [UNRESOLVED_METHOD] if declared is None else declared
    return [(method, route, handler) for method in methods]


def _registered_route_constructor(
    call: ast.Call, bindings: dict[str, ast.AST]
) -> list[tuple[str, str, str]]:
    """Discover Starlette ``Route`` objects passed through an app constructor."""
    if isinstance(call.func, ast.Name):
        name = call.func.id
    elif isinstance(call.func, ast.Attribute):
        name = call.func.attr
    else:
        return []
    if name not in {"Route", "WebSocketRoute"}:
        return []
    path_node = call.args[0] if call.args else None
    route = _static_string(path_node, bindings) if path_node is not None else None
    route = route if route is not None else DYNAMIC_ROUTE
    handler = _registration_endpoint(call)
    if name == "WebSocketRoute":
        return [(WEBSOCKET_METHOD, route, handler)]
    declared = _static_methods(call, bindings)
    methods = [UNRESOLVED_METHOD] if declared is None else declared
    return [(method, route, handler) for method in methods]


_OBSERVABILITY_CALLS = {
    "count",
    "debug",
    "error",
    "exception",
    "gauge",
    "histogram",
    "increment",
    "info",
    "log",
    "metric",
    "observe",
    "record",
    "time",
    "timing",
    "track",
    "warning",
}
_OBSERVABILITY_BUILDERS = {"bind", "labels", "new", "opt", "with_labels"}


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr.lower()
    if isinstance(call.func, ast.Name):
        return call.func.id.lower()
    return ""


def _expression_has_effect(node: ast.AST | None) -> bool:
    """Find a non-observability call in an executed expression."""
    if node is None:
        return False

    class EffectVisitor(ast.NodeVisitor):
        found = False

        def visit_Call(self, call: ast.Call) -> None:
            name = _call_name(call)
            if name not in _OBSERVABILITY_CALLS:
                self.found = True
            # Do not mistake a logger/metrics builder in a chained call such
            # as ``logger.bind(...).info(...)`` for domain work. Arguments
            # still need visiting because they may contain a real operation.
            if (
                name in _OBSERVABILITY_CALLS
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Call)
                and _call_name(call.func.value) in _OBSERVABILITY_BUILDERS
            ):
                builder = call.func.value
                for argument in (
                    *call.args,
                    *(keyword.value for keyword in call.keywords),
                    *builder.args,
                    *(keyword.value for keyword in builder.keywords),
                ):
                    self.visit(argument)
                return
            self.generic_visit(call)

        def visit_FunctionDef(self, _node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, _node: ast.AsyncFunctionDef) -> None:
            return

        def visit_Lambda(self, _node: ast.Lambda) -> None:
            return

    visitor = EffectVisitor()
    visitor.visit(node)
    return visitor.found


def _success_status(value: ast.AST | None) -> str | None:
    if not isinstance(value, ast.Dict):
        return None
    for key, item in zip(value.keys, value.values, strict=True):
        if (
            isinstance(key, ast.Constant)
            and key.value == "status"
            and isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            and item.value.lower() in SUCCESS_STATUS
        ):
            return item.value.lower()
    return None


def _simple_statement_has_effect(statement: ast.stmt) -> bool:
    """Check executed statements without treating branch predicates as effects."""
    if isinstance(
        statement,
        (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.NamedExpr),
    ):
        return _expression_has_effect(statement)
    return False


def _flow_block(statements: list[ast.stmt], incoming: set[bool]) -> tuple[set[bool], str | None]:
    """Return states reaching the next statement and the first fake return.

    The boolean state records whether every path considered so far has seen an
    effect call.  Branch predicates are deliberately not effects: a call such
    as ``feature_enabled()`` does not justify a success response on the path
    where the feature is disabled.
    """
    states = incoming
    for statement in statements:
        if not states:
            break
        states, status = _flow_statement(statement, states)
        if status is not None:
            return states, status
    return states, None


def _flow_statement(statement: ast.stmt, incoming: set[bool]) -> tuple[set[bool], str | None]:  # noqa: C901
    if isinstance(statement, ast.Return):
        status = _success_status(statement.value)
        if (
            status is not None
            and any(not effect for effect in incoming)
            and not _expression_has_effect(statement.value)
        ):
            return set(), status
        return set(), None
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return incoming, None
    if isinstance(statement, (ast.Raise, ast.Break, ast.Continue)):
        return set(), None
    if isinstance(statement, ast.If):
        body_states, body_status = _flow_block(statement.body, incoming)
        if body_status is not None:
            return set(), body_status
        if statement.orelse:
            else_states, else_status = _flow_block(statement.orelse, incoming)
        else:
            else_states, else_status = incoming, None
        if else_status is not None:
            return set(), else_status
        return body_states | else_states, None
    if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
        # A loop may execute zero times, but returns inside the body still
        # need inspection and a domain operation in the body justifies the
        # shared response after the loop.
        body_states, body_status = _flow_block(statement.body, incoming)
        if body_status is not None:
            return set(), body_status
        # A loop body is the domain operation even when the collection is
        # empty; retain that evidence for the shared return after the loop.
        loop_states = {True} if True in body_states else incoming | body_states
        if statement.orelse:
            loop_states, else_status = _flow_block(statement.orelse, loop_states)
            if else_status is not None:
                return set(), else_status
        return loop_states, None
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        context_effect = any(_expression_has_effect(item.context_expr) for item in statement.items)
        body_states, status = _flow_block(
            statement.body,
            {True} if context_effect else incoming,
        )
        return body_states, status
    if isinstance(statement, ast.Match):
        states = incoming
        for case in statement.cases:
            case_states, status = _flow_block(case.body, incoming)
            if status is not None:
                return set(), status
            states |= case_states
        return states, None
    if isinstance(statement, ast.Try):
        body_states, status = _flow_block(statement.body, incoming)
        if status is not None:
            return set(), status
        states = body_states
        if statement.orelse:
            states, status = _flow_block(statement.orelse, states)
            if status is not None:
                return set(), status
        for handler in statement.handlers:
            handler_states, status = _flow_block(handler.body, incoming)
            if status is not None:
                return set(), status
            states |= handler_states
        if statement.finalbody:
            states, status = _flow_block(statement.finalbody, states)
            if status is not None:
                return set(), status
        return states, None
    if _simple_statement_has_effect(statement):
        return {True}, None
    return incoming, None


def _returned_status(
    node: ast.AsyncFunctionDef | ast.FunctionDef | ast.Lambda | None,
) -> str | None:
    """Return a success-shaped status reachable without an effect on its path."""
    if node is None:
        return None
    if isinstance(node, ast.Lambda):
        status = _success_status(node.body)
        return status if status is not None and not _expression_has_effect(node.body) else None
    _flow_states, status = _flow_block(node.body, {False})
    return status


def _source_surfaces(path: Path, repo_root: Path) -> list[BackendSurface]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    source = path.relative_to(repo_root).as_posix()
    bindings = _module_bindings(tree)
    aliases = _module_aliases(tree, bindings)
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    surfaces: list[BackendSurface] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        status = _returned_status(node)
        obvious_fake = status is not None
        for method, route in _decorated_routes(node, bindings, aliases):
            surfaces.append(
                BackendSurface(
                    source=source,
                    method=method,
                    route=route,
                    handler=node.name,
                    obvious_fake_success=obvious_fake,
                )
            )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        registrations = [
            *_registered_routes(node, bindings, aliases),
            *_registered_route_constructor(node, bindings),
        ]
        for method, route, handler in registrations:
            endpoint = _registration_endpoint_node(node)
            if isinstance(endpoint, ast.Lambda):
                function: ast.AsyncFunctionDef | ast.FunctionDef | ast.Lambda | None = endpoint
            elif isinstance(endpoint, ast.Name):
                bound = bindings.get(endpoint.id)
                function = bound if isinstance(bound, ast.Lambda) else functions.get(endpoint.id)
            else:
                function = functions.get(handler)
            status = _returned_status(function)
            surfaces.append(
                BackendSurface(
                    source=source,
                    method=method,
                    route=route,
                    handler=handler,
                    obvious_fake_success=status is not None,
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


def _mutating_fetches(text: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for match in _FETCH_RE.finditer(text):
        method_match = _METHOD_RE.search(match.group("opts"))
        if method_match:
            found.add((method_match.group("method").upper(), match.group("route")))
    for match in _CLIENT_METHOD_RE.finditer(text):
        found.add((match.group("method").upper(), match.group("route")))
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
        if entry.get("signal") in {"timer-status-simulation", "mutating-api-call"}
    }

    errors = [*duplicate_backend, *duplicate_frontend]
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
