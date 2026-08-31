"""Truthful shipped-surface inventory for M1 Gate D (#465)."""

from __future__ import annotations

import ast
import json
import re
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
_FRONTEND_STATUS_RE = re.compile(
    r"\b(?:complete|completed|success|succeeded|building|running|progress)\b",
    re.IGNORECASE,
)


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
class FrontendSignal:
    source: str
    signal: str

    @property
    def key(self) -> str:
        return f"{self.source}:{self.signal}"


def load_matrix(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("surface matrix schema_version must be 1")
    return raw


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


def _decorated_routes(
    node: ast.AsyncFunctionDef | ast.FunctionDef,
) -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(
            decorator.func, ast.Attribute
        ):
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


def discover_backend_surfaces(
    repo_root: Path, roots: list[str]
) -> list[BackendSurface]:
    surfaces: list[BackendSurface] = []
    for root_name in roots:
        root = repo_root / root_name
        if not root.is_dir():
            raise ValueError(f"backend surface root does not exist: {root_name}")
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.relative_to(root).parts:
                continue
            surfaces.extend(_source_surfaces(path, repo_root))
    return sorted(set(surfaces))


def discover_frontend_signals(
    repo_root: Path, roots: list[str]
) -> list[FrontendSignal]:
    signals: list[FrontendSignal] = []
    for root_name in roots:
        root = repo_root / root_name
        if not root.is_dir():
            raise ValueError(f"frontend surface root does not exist: {root_name}")
        paths = (*root.rglob("*.ts"), *root.rglob("*.tsx"))
        for path in sorted(paths):
            if any(
                part in {"tests", "__tests__"}
                for part in path.relative_to(root).parts
            ):
                continue
            if ".test." in path.name or ".spec." in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            if "setTimeout" not in text or not _FRONTEND_STATUS_RE.search(text):
                continue
            signals.append(
                FrontendSignal(
                    source=path.relative_to(repo_root).as_posix(),
                    signal="timer-status-simulation",
                )
            )
    return sorted(set(signals))


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
    return f"{entry.get('source', '')}:{entry.get('signal', '')}"


def _validate_entry(entry: dict[str, Any], *, strict: bool) -> list[str]:
    errors: list[str] = []
    disposition = entry.get("disposition")
    if disposition not in VALID_DISPOSITIONS:
        errors.append(f"invalid disposition {disposition!r}")
        return errors
    if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
        errors.append("missing reason")
    if disposition == "unresolved" and not isinstance(entry.get("owner_issue"), int):
        errors.append("unresolved surface must name owner_issue")
    if (
        strict
        and disposition == "unresolved"
        and entry.get("production_enabled") is True
    ):
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


def validate_matrix(
    repo_root: Path, matrix: dict[str, Any], *, strict: bool = False
) -> list[str]:
    errors: list[str] = []
    backend = discover_backend_surfaces(repo_root, list(matrix.get("backend_roots", [])))
    frontend = discover_frontend_signals(
        repo_root, list(matrix.get("frontend_roots", []))
    )

    backend_entries, duplicate_backend = _index_entries(
        list(matrix.get("backend_surfaces", [])), _backend_entry_key, "backend"
    )
    frontend_entries, duplicate_frontend = _index_entries(
        list(matrix.get("frontend_surfaces", [])), _frontend_entry_key, "frontend"
    )
    errors.extend(duplicate_backend)
    errors.extend(duplicate_frontend)

    discovered_backend = {surface.key: surface for surface in backend}
    discovered_frontend = {signal.key: signal for signal in frontend}

    for key in sorted(discovered_backend.keys() - backend_entries.keys()):
        errors.append(f"unclassified backend surface: {key}")
    for key in sorted(backend_entries.keys() - discovered_backend.keys()):
        errors.append(f"stale backend surface entry: {key}")

    auto_frontend_entries = {
        key: entry
        for key, entry in frontend_entries.items()
        if entry.get("signal") == "timer-status-simulation"
    }
    for key in sorted(discovered_frontend.keys() - auto_frontend_entries.keys()):
        errors.append(f"unclassified frontend execution signal: {key}")
    for key in sorted(auto_frontend_entries.keys() - discovered_frontend.keys()):
        errors.append(f"stale frontend execution signal: {key}")

    for key, entry in sorted(backend_entries.items()):
        for error in _validate_entry(entry, strict=strict):
            errors.append(f"{key}: {error}")
        surface = discovered_backend.get(key)
        if surface and surface.obvious_fake_success and entry.get("disposition") not in {
            "disabled",
            "unresolved",
        }:
            errors.append(
                f"{key}: obvious success-shaped no-op cannot be "
                f"{entry.get('disposition')}"
            )

    for key, entry in sorted(frontend_entries.items()):
        for error in _validate_entry(entry, strict=strict):
            errors.append(f"{key}: {error}")
        source = repo_root / str(entry.get("source", ""))
        if not source.is_file():
            errors.append(f"{key}: frontend source does not exist")
        if entry.get("signal") == "timer-status-simulation" and entry.get(
            "disposition"
        ) not in {"disabled", "unresolved"}:
            errors.append(
                f"{key}: timer-driven execution state cannot be "
                f"{entry.get('disposition')}"
            )

    return errors


def format_errors(errors: list[str]) -> str:
    if not errors:
        return "Shipped-surface truth matrix is complete."
    return "Shipped-surface truth matrix failed:\n" + "\n".join(
        f"  - {error}" for error in errors
    )
