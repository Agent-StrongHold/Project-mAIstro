"""Tamper-evident Sentinel decision records (ADR-073 / issue #69).

The signing key is held only by the process that makes decisions.  Each record
stores the algorithm, verification-key reference (``key_id``), signature, and
public verification key; none of those fields can recreate the private key.
The record-side types live in :mod:`maistro.security.integrity_types`, which is
cryptography-free so importing a type module never pulls in a crypto backend.

Two verification modes exist on purpose:

* **embedded** — :func:`verify_decision` with no keyring resolves the record's
  own public key. It proves the record was not corrupted or edited in place,
  which is what a reader who holds no out-of-band material can check.
* **pinned** — a verifier that holds an independently trusted keyring (see
  :meth:`DecisionSigner.keyring`) passes it as ``trusted_keys``. Only this mode
  resists a writer who replaces *both* the public key and the signature, because
  the key the record claims is checked against the reference the verifier
  already trusts. ADR-073 names that reference as part of the contract, so
  production verifiers must pin.

:class:`DecisionSigner` keeps a verification history so rotated keys remain
trusted by an in-process verifier, and drops retired *private* material at
rotation so the record it protects can never carry the key that signed it.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from maistro.security.integrity_types import DecisionSignature, VerificationKey

_ALGORITHM = "Ed25519"
#: Raw Ed25519 public keys are 32 bytes; anything else is not a key this
#: mechanism can resolve, and must read as an unknown key rather than a
#: signature mismatch.
_PUBLIC_KEY_BYTES = 32


class IntegrityStatus(StrEnum):
    """How verification of one durable decision record resolved.

    ``UNSIGNED`` exists so a historical record written before signing landed is
    *labeled unverifiable* instead of being silently reported as invalid — or,
    worse, retroactively presented as signed.
    """

    VERIFIED = "verified"
    UNSIGNED = "unsigned"
    UNSUPPORTED_ALGORITHM = "unsupported_algorithm"
    UNKNOWN_KEY = "unknown_key"
    INVALID_SIGNATURE = "invalid_signature"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat()
    return str(value)


def canonical_decision_payload(record: Any) -> bytes:
    """Serialize all decision-bearing fields deterministically.

    The signature is deliberately calculated without the ``integrity`` field,
    allowing a verifier to reconstruct the exact signed bytes from a row read
    from a durable store.  Identity, timestamp, payload, and policy snapshot
    are explicit fields rather than incidental string formatting.
    """

    violations = []
    for violation in getattr(record, "violations", ()) or ():
        violations.append(
            {
                "boundary": getattr(violation, "boundary", ""),
                "rule": getattr(violation, "rule", ""),
                "severity": getattr(violation, "severity", ""),
                "detail": getattr(violation, "detail", ""),
                "repair_action": getattr(violation, "repair_action", None),
            }
        )
    payload = {
        "schema": 1,
        "timestamp": _timestamp(getattr(record, "timestamp", "")),
        "boundary": getattr(record, "boundary", ""),
        "identity": {
            "user_id": getattr(record, "user_id", ""),
            "org_id": getattr(record, "org_id", ""),
            "principal_id": getattr(record, "principal_id", ""),
            "team_id": getattr(record, "team_id", ""),
            "agent_id": getattr(record, "agent_id", ""),
        },
        "action": getattr(record, "action", "") or getattr(record, "tool_name", ""),
        "tool_name": getattr(record, "tool_name", "") or "",
        "verdict": getattr(record, "verdict", ""),
        "detail": getattr(record, "detail", ""),
        "policy_snapshot": getattr(record, "policy_snapshot", ""),
        "payload": getattr(record, "payload", ""),
        "inputs_hash": getattr(record, "inputs_hash", ""),
        "violations": violations,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


class DecisionSigner:
    """Ed25519 signer with explicit rotation and verification history."""

    def __init__(self, private_key: Ed25519PrivateKey | None = None) -> None:
        self._private_keys: dict[str, Ed25519PrivateKey] = {}
        self._public_keys: dict[str, bytes] = {}
        self._active_key_id = ""
        self._install(private_key or Ed25519PrivateKey.generate())

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    @property
    def keyring(self) -> dict[str, str]:
        """The publishable verification-key reference set (never private material).

        A deployment exposes this to verifiers out of band; a verifier that
        passes it as ``trusted_keys`` gets the tamper-evidence ADR-073 asks for,
        including across a restart of the signing process.
        """
        return {key_id: _b64(public_key) for key_id, public_key in self._public_keys.items()}

    @property
    def verification_history(self) -> tuple[VerificationKey, ...]:
        return tuple(
            VerificationKey(
                key_id=key_id,
                algorithm=_ALGORITHM,
                public_key=_b64(public_key),
                active=key_id == self._active_key_id,
            )
            for key_id, public_key in self._public_keys.items()
        )

    def _install(self, private_key: Ed25519PrivateKey) -> str:
        previous_key_id = self._active_key_id
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        key_id = f"sentinel-{hashlib.sha256(public_key).hexdigest()[:16]}"
        self._private_keys[key_id] = private_key
        self._public_keys[key_id] = public_key
        self._active_key_id = key_id
        # Retain retired public material for verification, never retired private
        # material. This is both the rotation boundary and the secret-retention
        # guarantee for an in-process signer.
        if previous_key_id:
            self._private_keys.pop(previous_key_id, None)
        return key_id

    def rotate(self, private_key: Ed25519PrivateKey | None = None) -> str:
        """Install a new active key and retain the old public key for history."""
        return self._install(private_key or Ed25519PrivateKey.generate())

    def sign(self, record: Any) -> DecisionSignature:
        key_id = self._active_key_id
        signature = self._private_keys[key_id].sign(canonical_decision_payload(record))
        return DecisionSignature(
            key_id=key_id,
            algorithm=_ALGORITHM,
            signature=_b64(signature),
            public_key=_b64(self._public_keys[key_id]),
        )

    def status(self, record: Any) -> IntegrityStatus:
        """Verify against this signer's own keyring, including retired keys."""
        return inspect_decision(record, trusted_keys=self.keyring)

    def verify(self, record: Any) -> bool:
        """True only when :meth:`status` resolves to ``VERIFIED``."""
        return self.status(record) is IntegrityStatus.VERIFIED


def _verify(public_key: bytes, payload: bytes, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(_unb64(signature), payload)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def inspect_decision(
    record: Any,
    *,
    trusted_keys: Mapping[str, str] | None = None,
) -> IntegrityStatus:
    """Resolve one record's integrity, optionally against a pinned keyring.

    ``trusted_keys`` maps a verification-key reference (``key_id``) to the
    base64url raw public key an independent source says that reference holds.
    When it is supplied, a record naming an unknown reference — or carrying a
    public key that disagrees with the pinned one — is ``UNKNOWN_KEY``: a
    store-writing attacker cannot swap in their own key and re-sign.
    """
    material = getattr(record, "integrity", None)
    if material is None:
        return IntegrityStatus.UNSIGNED
    if material.algorithm != _ALGORITHM:
        return IntegrityStatus.UNSUPPORTED_ALGORITHM
    try:
        public_key = _unb64(material.public_key)
    except (ValueError, TypeError):
        return IntegrityStatus.UNKNOWN_KEY
    if len(public_key) != _PUBLIC_KEY_BYTES:
        return IntegrityStatus.UNKNOWN_KEY
    if trusted_keys is not None:
        pinned = trusted_keys.get(material.key_id)
        if pinned is None:
            return IntegrityStatus.UNKNOWN_KEY
        try:
            if _unb64(pinned) != public_key:
                return IntegrityStatus.UNKNOWN_KEY
        except (ValueError, TypeError):
            return IntegrityStatus.UNKNOWN_KEY
    if not _verify(public_key, canonical_decision_payload(record), material.signature):
        return IntegrityStatus.INVALID_SIGNATURE
    return IntegrityStatus.VERIFIED


def verify_decision(
    record: Any,
    *,
    trusted_keys: Mapping[str, str] | None = None,
) -> bool:
    """True only when :func:`inspect_decision` resolves to ``VERIFIED``.

    Unsigned, unknown-key, wrong-algorithm and forged records all read False;
    call :func:`inspect_decision` when the *reason* matters — an unsigned
    historical record must be reported as unverifiable, not as tampered.
    """
    return inspect_decision(record, trusted_keys=trusted_keys) is IntegrityStatus.VERIFIED


__all__ = [
    "DecisionSignature",
    "DecisionSigner",
    "IntegrityStatus",
    "VerificationKey",
    "canonical_decision_payload",
    "inspect_decision",
    "verify_decision",
]
