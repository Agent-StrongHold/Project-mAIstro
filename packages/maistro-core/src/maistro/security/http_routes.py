"""Shared exact route-policy matching for HTTP authorization boundaries.

The quality route registry is a declaration gate, not a second product policy.
Both live backends use this matcher so an absent or ambiguous declaration has
one fail-closed meaning while each application retains its existing principal
and resource authorization rules.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*$")
_ROUTE_KINDS = frozenset({"exact", "prefix", "template"})
_ACCESS_KINDS = frozenset({"public", "permission", "exempt"})
_REGISTRY_RELPATH = ("quality", "route-permissions.json")


class RoutePolicyError(RuntimeError):
    """The shared route declaration cannot be used safely."""


def locate_route_registry(start: Path) -> Path:
    """Find ``quality/route-permissions.json`` from an app file's location.

    Tolerates both run layouts: the monorepo checkout (a backend middleware
    several levels under the repository root) and packaged images (e.g.
    ``/app/backend/middleware/auth.py`` with the registry copied to
    ``/app/quality/``), where only two parent levels exist and indexed
    ``parents[n]`` access would raise ``IndexError``. Raises
    :class:`RoutePolicyError` when no parent carries the registry: a
    deployment without reviewed declarations must fail closed at startup, not
    serve an unclassified route surface.
    """
    for parent in start.resolve().parents:
        candidate = parent.joinpath(*_REGISTRY_RELPATH)
        if candidate.is_file():
            return candidate
    raise RoutePolicyError(
        f"route authorization registry not found in any parent of {start} "
        f"(looked for {'/'.join(_REGISTRY_RELPATH)})"
    )


def _methods_are_valid(methods: object) -> bool:
    """A declaration must name at least one concrete HTTP method."""
    return (
        isinstance(methods, list)
        and bool(methods)
        and all(isinstance(method, str) for method in methods)
    )


def _shape_error(entry: dict[str, Any], where: str) -> str | None:
    """Validate the declaration's routing shape: path, kind, methods, access."""
    if not isinstance(entry.get("path"), str) or not entry["path"].startswith("/"):
        return f"{where} has an invalid path"
    if entry.get("kind") not in _ROUTE_KINDS:
        return f"{where} has an invalid kind"
    if not _methods_are_valid(entry.get("methods")):
        return f"{where} has invalid methods"
    if entry.get("access") not in _ACCESS_KINDS:
        return f"{where} has invalid access"
    return None


def _access_error(entry: dict[str, Any], where: str) -> str | None:
    """Validate the declaration's access decision for its declared kind."""
    if entry["access"] == "permission":
        permission = entry.get("permission")
        if not isinstance(permission, str) or _PERMISSION_RE.fullmatch(permission) is None:
            return f"{where} has an invalid permission"
        return None
    if entry["access"] == "exempt" and any(
        not isinstance(entry.get(field), str) or not entry[field].strip()
        for field in ("owner", "reason", "expires")
    ):
        return f"{where} has an incomplete exemption"
    return None


def _declaration_error(entry: Any, application: str, index: int) -> str | None:
    """One reason a route declaration is unusable, or ``None`` when it is valid."""
    where = f"route declaration {application}[{index}]"
    if not isinstance(entry, dict):
        return f"{where} is not an object"
    return _shape_error(entry, where) or _access_error(entry, where)


def load_route_policy(path: Path, application: str) -> tuple[dict[str, Any], ...]:
    """Load and validate one application's reviewed route declarations."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        routes = loaded["routes"][application]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RoutePolicyError(f"route authorization registry unavailable: {exc}") from exc
    if not isinstance(routes, list):
        raise RoutePolicyError(f"route authorization registry has no {application!r} list")

    validated: list[dict[str, Any]] = []
    for index, entry in enumerate(routes):
        error = _declaration_error(entry, application, index)
        if error is not None:
            raise RoutePolicyError(error)
        validated.append(entry)
    return tuple(validated)


def matches_prefix(path: str, prefix: str) -> bool:
    boundary = prefix.rstrip("/")
    return path == boundary or path.startswith(boundary + "/")


def _matches_template(path: str, template: str) -> bool:
    pattern = re.sub(r"\{[^/{}]+\}", r"[^/]+", template)
    return re.fullmatch(pattern.rstrip("/"), path.rstrip("/")) is not None


def _declaration_matches(entry: dict[str, Any], method: str, path: str) -> bool:
    """Whether one declaration governs this method and path."""
    if method not in entry.get("methods", []) and "*" not in entry.get("methods", []):
        return False
    if entry["kind"] == "exact":
        return bool(path == entry["path"])
    if entry["kind"] == "prefix":
        return bool(matches_prefix(path, entry["path"]))
    return bool(_matches_template(path, entry["path"]))


def _specificity(entry: dict[str, Any]) -> tuple[int, bool]:
    """Longer declared paths are more specific; exact beats prefix at a tie."""
    return (len(entry["path"]), entry["kind"] == "exact")


def route_policy(
    entries: tuple[dict[str, Any], ...], method: str, path: str
) -> dict[str, Any] | None:
    """Select the most-specific declaration, rejecting equally specific ties.

    FastAPI serves HEAD through a GET route, so a GET declaration also governs
    its implicit HEAD dispatch without requiring a duplicate registry entry.
    """
    method = "GET" if method.upper() == "HEAD" else method.upper()
    matches = [entry for entry in entries if _declaration_matches(entry, method, path)]
    if not matches:
        return None
    matches.sort(key=_specificity, reverse=True)
    selected = matches[0]
    if len(matches) > 1 and all(
        _specificity(entry) == _specificity(selected) for entry in matches[1:]
    ):
        return None
    return selected


__all__ = [
    "RoutePolicyError",
    "load_route_policy",
    "locate_route_registry",
    "matches_prefix",
    "route_policy",
]
