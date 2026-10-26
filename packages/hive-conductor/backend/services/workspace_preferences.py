"""Workspace product preferences on the canonical user profile (#1050).

These keys live in ``profile_store`` preferences — the same document UI,
``PUT``/``PATCH /v1/profile``, and chat ``profile_set`` already share. This
module is the allow-list and normalize path so a bad or hostile value cannot
steer the SPA off an in-app surface or invent a second settings owner.

Consumption of ``workspace_restore_aggressiveness`` (recent-return restore)
is applied by the SPA landing redirect (`DefaultLandingRedirect` +
`decideLanding` in ``frontend/src/lib/landing.ts``, #1050/#1822). This module
owns the durable preference contract only.
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

#: Absolute absence windows (ms) per band — lockstep with frontend landing.ts.
RESTORE_ABSOLUTE_MS: dict[str, int] = {
    "off": 0,
    "brief": 15 * 60 * 1000,
    "balanced": 4 * 60 * 60 * 1000,
    "generous": 24 * 60 * 60 * 1000,
}

#: Surfaces recent-return may reopen — lockstep with frontend RESTORE_SURFACES.
RESTORE_SURFACES: frozenset[str] = frozenset(
    {
        *ALLOWED_LANDING_PATHS,
        "/attention",
        "/approvals",
        "/capabilities",
        "/dag-runs",
        "/dags",
    }
)

#: Minimum consistent immediate hops before a learned-landing proposal
#: (lockstep with frontend LEARNED_STREAK_MIN).
LEARNED_STREAK_MIN = 3


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


def restore_window_ms(
    aggressiveness: str,
    *,
    left_at_ms: int,
    session_started_at_ms: int,
) -> int:
    """Absolute (+ proportional for balanced/generous) restore window in ms."""
    band = normalize_restore_aggressiveness(aggressiveness)
    absolute = RESTORE_ABSOLUTE_MS[band]
    if band in {"balanced", "generous"} and 0 < session_started_at_ms <= left_at_ms:
        session_len = left_at_ms - session_started_at_ms
        proportion = 1.0 if band == "generous" else 0.5
        return max(absolute, int(session_len * proportion))
    return absolute


def normalize_restore_path(raw: Any) -> str | None:
    """Normalize a recorded path into a restore-eligible surface, or None."""
    if not isinstance(raw, str):
        return None
    bare = raw.strip().split("?", 1)[0].split("#", 1)[0]
    if not bare.startswith("/") or "//" in bare or ".." in bare:
        return None
    if bare not in RESTORE_SURFACES:
        return None
    return bare


def decide_landing(
    *,
    aggressiveness: str,
    default_landing: str,
    recent: dict[str, Any] | None,
    now_ms: int,
) -> dict[str, str]:
    """Decide restore vs default landing — lockstep with frontend ``decideLanding``.

    Returns ``{"path": ..., "reason": "restore"|"default"|"off"|"stale"|"invalid"}``.
    """
    band = normalize_restore_aggressiveness(aggressiveness)
    default = normalize_landing_path(default_landing)
    if band == "off":
        return {"path": default, "reason": "off"}
    if not recent:
        return {"path": default, "reason": "default"}
    path = normalize_restore_path(recent.get("path"))
    if path is None:
        return {"path": default, "reason": "invalid"}
    try:
        left_at = int(recent["left_at_ms"])
        session_started = int(recent.get("session_started_at_ms", 0))
    except (KeyError, TypeError, ValueError):
        return {"path": default, "reason": "invalid"}
    if left_at > now_ms:
        return {"path": default, "reason": "invalid"}
    away_ms = max(0, now_ms - left_at)
    window_ms = restore_window_ms(band, left_at_ms=left_at, session_started_at_ms=session_started)
    if away_ms > window_ms:
        return {"path": default, "reason": "stale"}
    return {"path": path, "reason": "restore"}


def record_immediate_landing_hop(
    prior: dict[str, Any] | None,
    path: str,
    now_ms: int,
) -> dict[str, Any] | None:
    """Record an immediate Home→surface hop; return the updated streak pattern.

    Lockstep with frontend ``recordImmediateLandingHop``.
    """
    target = normalize_landing_path(path)
    if target == DEFAULT_LANDING_PATH:
        return prior
    if target not in ALLOWED_LANDING_PATHS:
        return prior
    if prior and prior.get("path") == target:
        try:
            streak = int(prior["streak"]) + 1
        except (KeyError, TypeError, ValueError):
            streak = 1
        return {"path": target, "streak": streak, "last_at_ms": now_ms}
    return {"path": target, "streak": 1, "last_at_ms": now_ms}


def decide_landing_suggestion(
    *,
    pattern: dict[str, Any] | None,
    explicit_default: str,
    suppressed_paths: set[str] | frozenset[str],
    streak_min: int = LEARNED_STREAK_MIN,
) -> tuple[bool, str]:
    """Decide whether to propose making ``pattern["path"]`` the default landing.

    Lockstep with frontend ``decideLandingSuggestion``. Returns
    ``(True, path)`` when a proposal should show, else ``(False, reason)``.
    """
    explicit = normalize_landing_path(explicit_default)
    if explicit != DEFAULT_LANDING_PATH:
        return False, "explicit"
    if not pattern:
        return False, "insufficient"
    path = normalize_landing_path(str(pattern.get("path", "")))
    if path == DEFAULT_LANDING_PATH or path not in ALLOWED_LANDING_PATHS:
        return False, "ineligible"
    if path in suppressed_paths:
        return False, "suppressed"
    try:
        streak = int(pattern["streak"])
    except (KeyError, TypeError, ValueError):
        return False, "insufficient"
    if streak < streak_min:
        return False, "insufficient"
    return True, path


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
