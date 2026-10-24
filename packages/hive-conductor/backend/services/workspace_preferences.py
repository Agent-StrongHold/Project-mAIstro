"""Workspace product preferences on the canonical user profile (#1050).

These keys live in ``profile_store`` preferences — the same document UI,
``PUT``/``PATCH /v1/profile``, and chat ``profile_set`` already share. This
module is the allow-list and normalize path so a bad or hostile value cannot
steer the SPA off an in-app surface or invent a second settings owner.

Consumption of ``workspace_restore_aggressiveness`` (recent-return restore)
belongs to the session-continuity path (#1822); this module only owns the
durable preference contract.
"""

from __future__ import annotations

from typing import Any

LANDING_KEY = "workspace_default_landing"
RESTORE_KEY = "workspace_restore_aggressiveness"

#: Surfaces a user may pin as their Workspace default. Home is the baseline.
ALLOWED_LANDING_PATHS: frozenset[str] = frozenset(
    {
        "/home",
        "/chat",
        "/goals",
        "/backlog",
        "/work-items",
    }
)

DEFAULT_LANDING_PATH = "/home"

#: How eagerly the product restores a prior surface after absence.
#: Exact windows are policy for the continuity consumer (#1822), not hard-coded
#: product law here — values only name the aggressiveness band.
ALLOWED_RESTORE_VALUES: frozenset[str] = frozenset(
    {
        "off",  # never restore; always use default landing
        "brief",  # short absolute window only
        "balanced",  # absolute + proportional (default)
        "generous",  # hold sessions longer / larger window
    }
)

DEFAULT_RESTORE_VALUE = "balanced"


class PreferenceValueError(ValueError):
    """A preference value is not in the Workspace allow-list."""


def normalize_landing_path(raw: Any) -> str:
    """Return a safe in-app landing path, or the Home baseline."""
    if not isinstance(raw, str):
        return DEFAULT_LANDING_PATH
    path = raw.strip().split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/") or "//" in path or ".." in path:
        return DEFAULT_LANDING_PATH
    if path not in ALLOWED_LANDING_PATHS:
        return DEFAULT_LANDING_PATH
    return path


def normalize_restore_aggressiveness(raw: Any) -> str:
    """Return a known aggressiveness band, or the balanced default."""
    if not isinstance(raw, str):
        return DEFAULT_RESTORE_VALUE
    value = raw.strip().lower()
    if value not in ALLOWED_RESTORE_VALUES:
        return DEFAULT_RESTORE_VALUE
    return value


def validate_preference_field(field: str, value: Any) -> Any:
    """Validate a single preference write.

    Unknown fields pass through unchanged (profile remains an open document for
    name/role/focus facts). Known Workspace keys must be allow-listed values;
    invalid values raise ``PreferenceValueError`` so the write is refused
    rather than silently coerced — the UI already normalizes before PATCH.
    """
    if field == LANDING_KEY:
        if not isinstance(value, str):
            raise PreferenceValueError(f"{LANDING_KEY} must be a path string")
        path = value.strip().split("?", 1)[0].split("#", 1)[0]
        if path not in ALLOWED_LANDING_PATHS:
            allowed = ", ".join(sorted(ALLOWED_LANDING_PATHS))
            raise PreferenceValueError(f"{LANDING_KEY} must be one of: {allowed}")
        return path
    if field == RESTORE_KEY:
        if not isinstance(value, str):
            raise PreferenceValueError(f"{RESTORE_KEY} must be a string")
        band = value.strip().lower()
        if band not in ALLOWED_RESTORE_VALUES:
            allowed = ", ".join(sorted(ALLOWED_RESTORE_VALUES))
            raise PreferenceValueError(f"{RESTORE_KEY} must be one of: {allowed}")
        return band
    return value


def validate_preferences_document(values: dict[str, Any]) -> dict[str, Any]:
    """Validate every known Workspace key in a full preferences replace."""
    out = dict(values)
    for key in (LANDING_KEY, RESTORE_KEY):
        if key in out:
            out[key] = validate_preference_field(key, out[key])
    return out
