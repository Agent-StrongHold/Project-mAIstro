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
    return any(part in EXCLUDED_PARTS for part in rel.parts) or ".test." in path.name or ".spec." in path.name


def _literal_methods(call: ast.Call) -> list[str]:
    for keyword in call.keywords:
        if keyword.arg != "methods":
            continue
        value = keyword.value
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return []
        methods: list[str] = []
        for item in value.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                methods.append(item.value.upper())
        return [method for method in methods if method in MUTATING_METHODS]
    return []


def _decorated_routes(node: ast.AsyncFunctionDef | ast.FunctionDef) -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        if not decorator.args:
            continue
        path = decorator.args[0]
        if not isinstance(path, ast.Constant) or not isinstance(path.value, str):
            continue
        name = decorator.func.attr.lower()
        methods = [name.upper()] if name.upper() in MUTATING_METHODS else []
        if name == "api_route":
            methods = _literal_methods(decorator)
        routes.extend((method, path.value) for method in methods)
    return routes


def _returned_status(node: ast.AsyncFunctionDef | ast.FunctionDef) -> str | None:
    # Deliberately conservative: a production handler is only called an obvious
    # fake when its entire body is a literal success-shaped return. More complex
    # handlers must be classified from evidence in the matrix, not guessed here.
    if len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
        return None
    value = node.body[0].value
    if not isinstance(value, ast.Dict):
        return None
    for key, item in zip(value.keys, value.values, strict=True):
        if not isinstance(key, ast.Constant) or key.value != "status":
            continue
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            return item.value.lower()
    return None


def _source_surfaces(path: Path, repo_root: Path) -> list[BackendSurface]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    source = path.relative_to(repo_root).as_posix()
    surfaces: list[BackendSurface] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        status = _returned_status(node)
        obvious_fake = status in SUCCESS_STATUS if status is not None else False
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
    errors = [
        f"{unclassified_label}: {key}"
        for key in sorted(discovered_keys - entry_keys)
    ]
    errors.extend(
        f"{stale_label}: {key}"
        for key in sorted(entry_keys - discovered_keys)
    )
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
