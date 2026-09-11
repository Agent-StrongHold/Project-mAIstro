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
    r"\b(?P<client>api|apiClient|client|http|httpClient)\s*\.\s*"
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


def _static_methods(call: ast.Call, bindings: dict[str, ast.AST]) -> list[str] | None:
    for keyword in call.keywords:
        if keyword.arg == "methods":
            value = _static_value(keyword.value, bindings)
            if not isinstance(value, list):
                return None
            return [method.upper() for method in value if method.upper() in MUTATING_METHODS]
    return []


def _literal_methods(call: ast.Call) -> list[str]:
    """Keep the old helper useful for callers while accepting constants too."""
    return _static_methods(call, {}) or []


def _module_aliases(tree: ast.Module, bindings: dict[str, ast.AST]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.AST):
            continue
        value = statement.value
        alias: str | None = None
        if isinstance(value, ast.Attribute):
            alias = value.attr.lower()
        elif (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "getattr"
            and len(value.args) >= 2
        ):
            alias = _static_string(value.args[1], bindings)
            alias = alias.lower() if alias is not None else None
        if alias is None:
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                aliases[target.id] = alias
    return aliases


def _route_decorator_name(decorator: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(decorator, ast.Attribute):
        return decorator.attr.lower()
    if isinstance(decorator, ast.Name):
        return aliases.get(decorator.id)
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
        name = _route_decorator_name(decorator.func, aliases)
        if name not in {
            "post",
            "put",
            "patch",
            "delete",
            "api_route",
            "websocket",
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
        if name == "websocket":
            methods = [WEBSOCKET_METHOD]
        elif name == "api_route":
            declared = _static_methods(decorator, bindings)
            # FastAPI defaults api_route to GET. An unresolved methods value
            # must remain visible because it may contain a mutating verb.
            methods = [UNRESOLVED_METHOD] if declared is None else declared
        else:
            methods = [name.upper()]
        routes.extend((method, route) for method in methods)
    return routes


def _registration_endpoint(call: ast.Call) -> str:
    endpoint: ast.AST | None = None
    if len(call.args) >= 2:
        endpoint = call.args[1]
    for keyword in call.keywords:
        if keyword.arg == "endpoint":
            endpoint = keyword.value
            break
    if isinstance(endpoint, ast.Name):
        return endpoint.id
    if isinstance(endpoint, ast.Attribute):
        return endpoint.attr
    if isinstance(endpoint, ast.Lambda):
        return "<lambda>"
    return "<dynamic>"


def _registered_routes(
    call: ast.Call, bindings: dict[str, ast.AST], aliases: dict[str, str] | None = None
) -> list[tuple[str, str, str]]:
    aliases = {} if aliases is None else aliases
    if isinstance(call.func, ast.Attribute):
        name = call.func.attr.lower()
    elif isinstance(call.func, ast.Name):
        name = aliases.get(call.func.id, "")
    else:
        return []
    if name not in {"add_api_route", "add_route", "add_api_websocket_route", "add_websocket_route"}:
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
    declared = _static_methods(call, bindings)
    # Both FastAPI and Starlette default a route registration without methods
    # to GET. An unresolved methods expression is fail-closed instead.
    methods = [UNRESOLVED_METHOD] if declared is None else declared
    return [(method, route, handler) for method in methods]


def _handler_has_effect_evidence(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    """Treat domain/execution calls as evidence, but not observability calls."""
    observability = {
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

    class EffectVisitor(ast.NodeVisitor):
        found = False

        def visit_Call(self, call: ast.Call) -> None:
            if isinstance(call.func, ast.Attribute):
                name = call.func.attr
            elif isinstance(call.func, ast.Name):
                name = call.func.id
            else:
                name = ""
            if name.lower() not in observability:
                self.found = True
            self.generic_visit(call)

        def visit_FunctionDef(self, _node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, _node: ast.AsyncFunctionDef) -> None:
            return

        def visit_Lambda(self, _node: ast.Lambda) -> None:
            return

    visitor = EffectVisitor()
    for statement in node.body:
        visitor.visit(statement)
        if visitor.found:
            return True
    return False


def _returned_status(  # noqa: C901
    node: ast.AsyncFunctionDef | ast.FunctionDef,
) -> str | None:
    """Return a success-shaped status found on any path in this handler."""

    class ReturnVisitor(ast.NodeVisitor):
        status: str | None = None

        def visit_Return(self, return_node: ast.Return) -> None:
            value = return_node.value
            if not isinstance(value, ast.Dict):
                return
            for key, item in zip(value.keys, value.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "status"
                    and isinstance(item, ast.Constant)
                    and isinstance(item.value, str)
                    and item.value.lower() in SUCCESS_STATUS
                ):
                    self.status = item.value.lower()
                    return

        def visit_FunctionDef(self, _node: ast.FunctionDef) -> None:
            # A nested function's return is not a return path of this handler.
            return

        def visit_AsyncFunctionDef(self, _node: ast.AsyncFunctionDef) -> None:
            return

        def visit_Lambda(self, _node: ast.Lambda) -> None:
            return

    visitor = ReturnVisitor()
    for statement in node.body:
        visitor.visit(statement)
        if visitor.status is not None:
            break
    if visitor.status is not None and not _handler_has_effect_evidence(node):
        return visitor.status
    return None


def _source_surfaces(path: Path, repo_root: Path) -> list[BackendSurface]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    source = path.relative_to(repo_root).as_posix()
    bindings = _module_bindings(tree)
    aliases = _module_aliases(tree, bindings)
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
        for method, route, handler in _registered_routes(node, bindings, aliases):
            function = next(
                (
                    candidate
                    for candidate in ast.walk(tree)
                    if isinstance(candidate, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and candidate.name == handler
                ),
                None,
            )
            status = _returned_status(function) if function is not None else None
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
