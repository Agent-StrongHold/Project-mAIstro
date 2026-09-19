"""Shared HTTP contract for task admission scope.

Workspace scope is an admission binding, not part of ``TaskCreate``. The
Conductor therefore carries an already-authorized Workspace across the
server-to-server boundary in a dedicated header. A second header proves that
the binding came from the trusted Hive service rather than from an ordinary
maistro-server API client; maistro-server verifies that proof before passing the
binding to the canonical ``WorkspaceRoutingAdmitter``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Literal

WORKSPACE_ID_HEADER = "X-Maistro-Workspace-Id"
WORKSPACE_SCOPE_SIGNATURE_HEADER = "X-Maistro-Workspace-Signature"
DELEGATION_HEADER = "X-Maistro-Delegation"
_SCOPE_SIGNATURE_DOMAIN = "maistro-workspace-scope:v1:"
_DELEGATION_DOMAIN = "maistro-task-delegation:v1"
_DELEGATION_AUDIENCE = "maistro-server"
_DELEGATION_TTL_SECONDS = 300
_DELEGATION_CLOCK_SKEW_SECONDS = 30


@dataclass(frozen=True)
class DelegationContext:
    """Host-authenticated identity for a Conductor -> server task request.

    The context is signed as a compact envelope, rather than treating a user
    id header or request body field as authority. The server still gets the
    service principal from bearer authentication and requires it to match this
    envelope's service claim.
    """

    service_principal: str
    originating_principal: str
    principal_kind: Literal["user", "system"]
    delegation_id: str
    issued_at: int
    expires_at: int


def _encode_delegation_payload(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_delegation_payload(encoded: str) -> dict[str, object]:
    padding = "=" * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
        payload = json.loads(raw)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid delegation envelope") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid delegation envelope")
    return payload


def sign_delegation_context(
    *,
    service_principal: str,
    originating_principal: str,
    key: str,
    principal_kind: Literal["user", "system"] = "user",
    delegation_id: str | None = None,
    now: int | None = None,
    ttl_seconds: int = _DELEGATION_TTL_SECONDS,
) -> str:
    """Sign one short-lived, audience-bound originating-principal envelope."""
    if not service_principal.strip() or not originating_principal.strip():
        raise ValueError("delegation principals must be non-empty")
    if not key:
        raise ValueError("delegation signing key must be configured")
    if principal_kind == "system" and originating_principal != "system":
        raise ValueError("system delegation must use the system principal")
    if ttl_seconds <= 0 or ttl_seconds > 3600:
        raise ValueError("delegation ttl must be between 1 and 3600 seconds")
    issued_at = int(time.time()) if now is None else now
    payload: dict[str, object] = {
        "aud": _DELEGATION_AUDIENCE,
        "exp": issued_at + ttl_seconds,
        "iat": issued_at,
        "kind": principal_kind,
        "jti": delegation_id or uuid.uuid4().hex,
        "service": service_principal,
        "sub": originating_principal,
        "v": 1,
    }
    encoded = _encode_delegation_payload(payload)
    signature = hmac.new(
        key.encode("utf-8"), f"{_DELEGATION_DOMAIN}.{encoded}".encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def _text_claim(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid delegation claims")
    return value


def _int_claim(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int):
        raise ValueError("invalid delegation timestamps")
    return value


def _delegation_claims(
    payload: dict[str, object],
) -> tuple[str, str, Literal["user", "system"], str, int, int]:
    if payload.get("v") != 1 or payload.get("aud") != _DELEGATION_AUDIENCE:
        raise ValueError("invalid delegation audience or version")
    service = _text_claim(payload, "service")
    subject = _text_claim(payload, "sub")
    kind = _text_claim(payload, "kind")
    delegation_id = _text_claim(payload, "jti")
    if kind == "user":
        principal_kind: Literal["user", "system"] = "user"
    elif kind == "system":
        principal_kind = "system"
    else:
        raise ValueError("invalid delegation principal kind")
    if principal_kind == "system" and subject != "system":
        raise ValueError("invalid system delegation principal")
    return (
        service,
        subject,
        principal_kind,
        delegation_id,
        _int_claim(payload, "iat"),
        _int_claim(payload, "exp"),
    )


def verify_delegation_context(
    token: str,
    key: str,
    *,
    now: int | None = None,
) -> DelegationContext:
    """Verify and decode a delegation envelope; invalid evidence fails closed."""
    if not key:
        raise ValueError("delegation verification key is not configured")
    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("invalid delegation envelope")
    encoded, signature = parts
    expected = hmac.new(
        key.encode("utf-8"), f"{_DELEGATION_DOMAIN}.{encoded}".encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid delegation signature")
    service, subject, kind, delegation_id, issued_at, expires_at = _delegation_claims(
        _decode_delegation_payload(encoded)
    )
    current = int(time.time()) if now is None else now
    if issued_at > current + _DELEGATION_CLOCK_SKEW_SECONDS or expires_at < current:
        raise ValueError("delegation envelope is expired or not yet valid")
    if expires_at <= issued_at or expires_at - issued_at > 3600:
        raise ValueError("invalid delegation lifetime")
    return DelegationContext(
        service_principal=service,
        originating_principal=subject,
        principal_kind=kind,
        delegation_id=delegation_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def sign_workspace_scope(workspace_id: str, key: str) -> str:
    """Return the domain-separated HMAC-SHA256 proof for one Workspace binding."""
    message = f"{_SCOPE_SIGNATURE_DOMAIN}{workspace_id}"
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_workspace_scope_signature(workspace_id: str, signature: str, key: str) -> bool:
    """Verify a Workspace binding without timing-sensitive string comparison."""
    expected = sign_workspace_scope(workspace_id, key)
    return hmac.compare_digest(signature, expected)


__all__ = [
    "DELEGATION_HEADER",
    "WORKSPACE_ID_HEADER",
    "WORKSPACE_SCOPE_SIGNATURE_HEADER",
    "DelegationContext",
    "sign_delegation_context",
    "sign_workspace_scope",
    "verify_delegation_context",
    "verify_workspace_scope_signature",
]
