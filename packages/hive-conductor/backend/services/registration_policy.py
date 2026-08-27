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


def set_policy(mode: RegistrationMode) -> dict[str, Any]:
    """Persist an operator-selected policy; invalid modes are never stored."""
    if mode not in _VALID_MODES:
        raise ValueError(f"unsupported registration mode: {mode}")
    record = {"mode": mode, "updated_at": _now().isoformat()}
    _kv()[_POLICY_KEY] = record
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


def invitation_is_valid(token: str | None) -> bool:
    """Validate an invitation without consuming it. Malformed state fails closed."""
    if not token:
        return False
    raw = _kv().get(_token_key(token))
    if not isinstance(raw, dict):
        return False
    expires_raw = raw.get("expires_at")
    if not isinstance(expires_raw, str):
        return False
    try:
        expires_at = datetime.fromisoformat(expires_raw)
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > _now()


def consume_invitation(token: str | None) -> bool:
    """Consume a valid invitation exactly once within this store instance."""
    if not invitation_is_valid(token):
        return False
    assert token is not None
    return _kv().pop(_token_key(token), None) is not None


def registration_allowed(invite_token: str | None = None) -> bool:
    """Open policy or a valid explicit invitation permits account creation."""
    return get_policy()["mode"] == "open" or invitation_is_valid(invite_token)
