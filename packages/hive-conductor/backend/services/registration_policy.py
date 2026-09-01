"""Durable, fail-closed registration policy for Hive Conductor (#313).

The setup marker already lives in ``stores.sessions``, a JsonStore backed by the
configured persistence layer. Registration policy lives beside that marker so a
restart cannot silently turn signup back on. Missing, malformed, or expired
state always means closed.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

_POLICY_KEY = "__registration_policy__"
_INVITE_PREFIX = "__registration_invite__:"
_VALID_MODES = frozenset({"closed", "open"})
RegistrationMode = Literal["closed", "open"]
_MISSING = object()


def _kv() -> Any:
    import stores

    return stores.sessions


def _now() -> datetime:
    return datetime.now(UTC)


def _token_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{_INVITE_PREFIX}{digest}"


def get_policy() -> dict[str, Any]:
    """Return the public registration policy, defaulting closed on bad state."""
    raw = _kv().get(_POLICY_KEY)
    if not isinstance(raw, dict) or raw.get("mode") not in _VALID_MODES:
        return {"mode": "closed"}
    return {"mode": raw["mode"]}


def _restore_local_policy_after_failed_write(kv: Any, previous: object) -> None:
    """Undo JsonStore's publish-before-persist mutation without another I/O attempt.

    ``JsonStore.__setitem__`` currently updates its local dictionary before the
    backing writer is called. If that writer raises, using ``pop``/``__setitem__``
    to roll back would invoke the same broken persistence path again. Registration
    is security policy, so restore only the already-mutated local cache and let
    the original persistence exception propagate. This is intentionally local to
    #313 rather than changing JsonStore semantics under other active state work.
    """
    data = getattr(kv, "_data", None)
    if not isinstance(data, dict):
        return
    if previous is _MISSING:
        data.pop(_POLICY_KEY, None)
    else:
        data[_POLICY_KEY] = previous


def set_policy(mode: RegistrationMode) -> dict[str, Any]:
    """Persist an operator-selected policy; failed persistence changes nothing."""
    if mode not in _VALID_MODES:
        raise ValueError(f"unsupported registration mode: {mode}")
    kv = _kv()
    previous: object = kv.get(_POLICY_KEY, _MISSING)
    record = {"mode": mode, "updated_at": _now().isoformat()}
    try:
        kv[_POLICY_KEY] = record
    except Exception:
        _restore_local_policy_after_failed_write(kv, previous)
        raise
    return {"mode": mode}


def create_invitation(*, ttl_seconds: int = 3600) -> dict[str, Any]:
    """Create a one-time invitation and return the plaintext token exactly once."""
    if ttl_seconds < 60 or ttl_seconds > 7 * 24 * 60 * 60:
        raise ValueError("invitation ttl must be between 60 seconds and 7 days")
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(seconds=ttl_seconds)
    _kv()[_token_key(token)] = {
        "expires_at": expires_at.isoformat(),
        "created_at": _now().isoformat(),
    }
    return {"token": token, "expires_at": expires_at.isoformat()}


def _valid_record(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    raw = _kv().get(_token_key(token))
    if not isinstance(raw, dict):
        return None
    expires_raw = raw.get("expires_at")
    if not isinstance(expires_raw, str):
        return None
    try:
        expires_at = datetime.fromisoformat(expires_raw)
    except ValueError:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= _now():
        return None
    return raw


def invitation_is_valid(token: str | None) -> bool:
    """Validate an invitation without consuming it. Malformed state fails closed."""
    return _valid_record(token) is not None


def claim_invitation(token: str | None) -> dict[str, Any] | None:
    """Remove and return a valid invitation before account creation begins."""
    record = _valid_record(token)
    if record is None or token is None:
        return None
    claimed = _kv().pop(_token_key(token), None)
    return claimed if isinstance(claimed, dict) else None


def restore_invitation(token: str | None, record: dict[str, Any] | None) -> None:
    """Restore a claimed invitation when downstream registration did not commit."""
    if token and record and _valid_record_from_value(record):
        _kv()[_token_key(token)] = record


def _valid_record_from_value(record: dict[str, Any]) -> bool:
    expires_raw = record.get("expires_at")
    if not isinstance(expires_raw, str):
        return False
    try:
        expires_at = datetime.fromisoformat(expires_raw)
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > _now()


def registration_allowed(invite_token: str | None = None) -> bool:
    """Open policy or a valid explicit invitation permits account creation."""
    return get_policy()["mode"] == "open" or invitation_is_valid(invite_token)
