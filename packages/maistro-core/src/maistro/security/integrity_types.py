"""Verification-material types for tamper-evident decision records (issue #69).

These are deliberately kept free of any cryptographic backend. ``AuditEntry``
exists in two mirrored type modules that almost every other subsystem imports,
and the signature material is one of their fields; if those types lived next to
the Ed25519 implementation, importing a type module would drag ``cryptography``
into the whole package graph — which is exactly how the mandatory-dependency
guarantee in ``tests/auth/test_mandatory_verification.py`` (#856) got broken.
Signing and verification live in ``security/sentinel/integrity.py`` and import
these types from here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionSignature:
    """Public verification material attached to one decision record."""

    key_id: str
    algorithm: str
    signature: str
    public_key: str


@dataclass(frozen=True)
class VerificationKey:
    """A non-secret entry in a signer's rotation history."""

    key_id: str
    algorithm: str
    public_key: str
    active: bool


__all__ = ["DecisionSignature", "VerificationKey"]
