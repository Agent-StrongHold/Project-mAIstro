"""Tamper-evident Sentinel decision records (ADR-073 / issue #69).

The signing key is held only by the process that makes decisions.  Each record
stores the algorithm, key id, signature, and public verification key; none of
those fields can recreate the private key.  Embedding the public key makes a
durable record independently verifiable, while :class:`DecisionSigner` keeps a
verification history so rotated keys remain trusted by an in-process verifier.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_ALGORITHM = "Ed25519"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class DecisionSignature:
    """Public verification material attached to one decision record."""

    key_id: str
    algorithm: str
    signature: str
    public_key: str


@dataclass(frozen=True)
class VerificationKey:
    """A non-secret entry in the signer's rotation history."""

    key_id: str
    algorithm: str
    public_key: str
    active: bool


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

    def verify(self, record: Any) -> bool:
        """Verify against this signer's known key history, including retired keys."""
        material = getattr(record, "integrity", None)
        if material is None or material.algorithm != _ALGORITHM:
            return False
        public_key = self._public_keys.get(material.key_id)
        if public_key is None or _b64(public_key) != material.public_key:
            return False
        return _verify(public_key, canonical_decision_payload(record), material.signature)


def _verify(public_key: bytes, payload: bytes, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(_unb64(signature), payload)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def verify_decision(record: Any) -> bool:
    """Verify a durable record using only its embedded public material."""
    material = getattr(record, "integrity", None)
    if material is None or material.algorithm != _ALGORITHM:
        return False
    try:
        return _verify(
            _unb64(material.public_key), canonical_decision_payload(record), material.signature
        )
    except (ValueError, TypeError):
        return False


__all__ = [
    "DecisionSignature",
    "DecisionSigner",
    "VerificationKey",
    "canonical_decision_payload",
    "verify_decision",
]
