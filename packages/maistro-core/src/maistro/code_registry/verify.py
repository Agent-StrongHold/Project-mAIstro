"""Signature verification for code registry entries (SPEC-257 / ADR-069)."""

from __future__ import annotations

from typing import Protocol

from cryptography.exceptions import InvalidSignature as _CryptoInvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class SignatureVerifier(Protocol):
    def verify(self, message: bytes, signature: bytes) -> bool: ...


class Ed25519Verifier:
    def __init__(self, public_key: bytes) -> None:
        self._public_key = Ed25519PublicKey.from_public_bytes(public_key)

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            self._public_key.verify(signature, message)
        except _CryptoInvalidSignature:
            return False
        return True
