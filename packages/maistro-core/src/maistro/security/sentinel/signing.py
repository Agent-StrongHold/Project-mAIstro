"""Tamper-evident signatures for Sentinel audit decisions.

The audit record is evidence, not merely a debug log.  This module keeps the
signing mechanism separate from the audit store so in-memory and durable stores
can use the same canonical bytes and verification contract.  The private key
is supplied by deployment configuration (or generated for an explicitly
short-lived in-memory/test log); it is never serialized into an audit entry.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import fields, is_dataclass, replace
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_SIGNING_KEY_ENV = "MAISTRO_AUDIT_SIGNING_KEY"
_PROOF_TYPE = "Ed25519Signature2020"
_SIGNATURE_FIELDS = frozenset({"signature", "signing_key_id", "proof_type"})
_CANONICAL_METADATA_FIELDS = frozenset({"timestamp"})


class AuditSignatureError(ValueError):
    """Raised when configured audit-signing material is malformed."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise AuditSignatureError("audit signature is not valid base64url") from exc


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if is_dataclass(value):
        return {
            item.name: _json_value(getattr(value, item.name))
            for item in fields(value)
            if item.name not in _SIGNATURE_FIELDS
        }
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    return value


def canonical_audit_bytes(entry: Any) -> bytes:
    """Return deterministic, signature-free bytes for one audit entry."""
    if not is_dataclass(entry):
        raise TypeError("audit entries must be dataclasses")
    payload: dict[str, Any] = {}
    for item in fields(entry):
        if item.name in _SIGNATURE_FIELDS or item.name in _CANONICAL_METADATA_FIELDS:
            continue
        value = getattr(entry, item.name)
        if item.name == "verdict" and value == "":
            value = "allowed"
        # Storage metadata and default-valued compatibility fields vary between
        # the Sentinel and persistence dataclasses. Omitting empty values lets
        # both representations verify the same decision bytes.
        if value in (None, "", (), [], frozenset()):
            continue
        payload[item.name] = _json_value(value)
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


class AuditSigner:
    """Ed25519 signer/verifier shared by Sentinel audit stores.

    ``from_environment`` accepts either a URL-safe base64 or hexadecimal
    32-byte Ed25519 seed.  Supplying the same external key after restart is
    required to verify durable records; the generated fallback is intentionally
    marked ephemeral and is suitable only for an in-memory/test store.
    """

    def __init__(self, private_key: bytes | None = None) -> None:
        if private_key is None:
            self._private_key = Ed25519PrivateKey.generate()
            self.ephemeral = True
        else:
            if len(private_key) != 32:
                raise AuditSignatureError("audit signing key must be exactly 32 bytes")
            self._private_key = Ed25519PrivateKey.from_private_bytes(private_key)
            self.ephemeral = False
        public = self._private_key.public_key().public_bytes_raw()
        self.key_id = hashlib.sha256(public).hexdigest()[:16]
        self._public_key = public

    @classmethod
    def from_environment(cls) -> AuditSigner:
        raw = os.environ.get(_SIGNING_KEY_ENV)
        if not raw:
            return cls()
        try:
            try:
                key = _unb64(raw.strip())
                if len(key) != 32:
                    raise ValueError
            except (AuditSignatureError, ValueError):
                key = bytes.fromhex(raw.strip())
        except ValueError as exc:
            raise AuditSignatureError(
                f"{_SIGNING_KEY_ENV} must be a 32-byte base64url or hexadecimal seed"
            ) from exc
        return cls(key)

    @property
    def public_key(self) -> bytes:
        """Return public verification material without exposing the private key."""
        return self._public_key

    def sign(self, entry: Any) -> Any:
        """Return ``entry`` with an Ed25519 proof attached."""
        signature = _b64(self._private_key.sign(canonical_audit_bytes(entry)))
        updates = {
            "signature": signature,
            "signing_key_id": self.key_id,
            "proof_type": _PROOF_TYPE,
        }
        # ``security._types.AuditEntry`` is mutable for compatibility with the
        # original Sentinel API, while ``types.security.AuditEntry`` is frozen.
        # Mutating the former preserves the old identity/equality behavior;
        # replacing the latter keeps the persistence type immutable.
        try:
            for name, value in updates.items():
                setattr(entry, name, value)
            return entry
        except (AttributeError, TypeError, ValueError):
            return replace(entry, **updates)

    def verify(self, entry: Any) -> bool:
        """Verify the proof and reject records signed by another key."""
        if getattr(entry, "signing_key_id", "") != self.key_id:
            return False
        if getattr(entry, "proof_type", "") != _PROOF_TYPE:
            return False
        signature = getattr(entry, "signature", "")
        if not signature:
            return False
        try:
            self._private_key.public_key().verify(_unb64(signature), canonical_audit_bytes(entry))
        except (AuditSignatureError, InvalidSignature, TypeError, ValueError):
            return False
        return True


__all__ = ["AuditSignatureError", "AuditSigner", "canonical_audit_bytes"]
