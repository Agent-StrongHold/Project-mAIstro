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


def load_route_policy(  # noqa: C901
    path: Path, application: str
) -> tuple[dict[str, Any], ...]:
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
        if not isinstance(entry, dict):
            raise RoutePolicyError(f"route declaration {application}[{index}] is not an object")
        if not isinstance(entry.get("path"), str) or not entry["path"].startswith("/"):
            raise RoutePolicyError(f"route declaration {application}[{index}] has an invalid path")
        if entry.get("kind") not in _ROUTE_KINDS:
            raise RoutePolicyError(f"route declaration {application}[{index}] has an invalid kind")
        methods = entry.get("methods")
        if (
            not isinstance(methods, list)
            or not methods
            or any(not isinstance(method, str) for method in methods)
        ):
            raise RoutePolicyError(f"route declaration {application}[{index}] has invalid methods")
        if entry.get("access") not in _ACCESS_KINDS:
            raise RoutePolicyError(f"route declaration {application}[{index}] has invalid access")
        if entry["access"] == "permission" and (
            not isinstance(entry.get("permission"), str)
            or _PERMISSION_RE.fullmatch(entry["permission"]) is None
        ):
            raise RoutePolicyError(
                f"route declaration {application}[{index}] has an invalid permission"
            )
        if entry["access"] == "exempt" and any(
            not isinstance(entry.get(field), str) or not entry[field].strip()
            for field in ("owner", "reason", "expires")
        ):
            raise RoutePolicyError(
                f"route declaration {application}[{index}] has an incomplete exemption"
            )
        validated.append(entry)
    return tuple(validated)


def matches_prefix(path: str, prefix: str) -> bool:
    boundary = prefix.rstrip("/")
    return path == boundary or path.startswith(boundary + "/")


def _matches_template(path: str, template: str) -> bool:
    pattern = re.sub(r"\{[^/{}]+\}", r"[^/]+", template)
    return re.fullmatch(pattern.rstrip("/"), path.rstrip("/")) is not None


def route_policy(
    entries: tuple[dict[str, Any], ...], method: str, path: str
) -> dict[str, Any] | None:
    """Select the most-specific declaration, rejecting equally specific ties.

    FastAPI serves HEAD through a GET route, so a GET declaration also governs
    its implicit HEAD dispatch without requiring a duplicate registry entry.
    """
    method = "GET" if method.upper() == "HEAD" else method.upper()
    matches = [
        entry
        for entry in entries
        if (method in entry.get("methods", []) or "*" in entry.get("methods", []))
        and (
            (entry["kind"] == "exact" and path == entry["path"])
            or (entry["kind"] == "prefix" and matches_prefix(path, entry["path"]))
            or (entry["kind"] == "template" and _matches_template(path, entry["path"]))
        )
    ]
    if not matches:
        return None
    matches.sort(key=lambda entry: (len(entry["path"]), entry["kind"] == "exact"), reverse=True)
    selected = matches[0]
    if len(matches) > 1 and all(
        (len(entry["path"]), entry["kind"] == "exact")
        == (len(selected["path"]), selected["kind"] == "exact")
        for entry in matches[1:]
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
