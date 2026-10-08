"""Digest/signing helpers for certification (M9-H3, #975).

The certification signature is an **Ed25519 signature over a canonical,
version-tagged payload** that names the extension identity and the two
digests that bind the report to bytes:

    maistro-extension-certification:v1
    <extension id>
    <extension version>
    <package sha256>
    <manifest sha256>

The shape deliberately parallels the canonical install payload the
product-side installer verifies (`maistro.extensions.verify`, M9-B1) — the
same identity triple, the same digest algorithm, a version tag that makes
replay of one format as the other impossible — so a registry can later
ingest a certification as *evidence* without this package becoming a
dependency of the product, and never as *authorization*: the report itself
says the consuming lifecycle must still run its own policy.

`cryptography` is an optional dependency (the ``signing`` extra): the
harness's default runtime stays standard-library only, and a signing
request without the extra fails **closed** with an actionable error, never
with a downgrade to "unsigned but claims signed".
"""

from __future__ import annotations

import hashlib
from typing import Any

__all__ = [
    "DIGEST_ALGORITHM",
    "SIGNING_EXTRA",
    "SigningUnavailable",
    "canonical_certification_payload",
    "generate_signing_key_hex",
    "public_key_hex_from_seed",
    "sign_payload",
    "verify_payload",
]

DIGEST_ALGORITHM = "sha256"

#: The pip extra that carries the signing implementation.
SIGNING_EXTRA = "signing"

_CERTIFICATION_PAYLOAD_TAG = "maistro-extension-certification:v1"


class SigningUnavailable(RuntimeError):
    """Signing was requested but the ``cryptography`` package is absent."""


def _require_cryptography() -> tuple[type[Any], type[Any]]:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise SigningUnavailable(
            "signing requires the 'cryptography' package; install it with: "
            f"pip install 'maistro-ext-harness[{SIGNING_EXTRA}]'"
        ) from exc
    return Ed25519PrivateKey, Ed25519PublicKey


def canonical_certification_payload(
    *,
    extension_id: str,
    version: str,
    package_sha256: str,
    manifest_sha256: str,
) -> bytes:
    """The exact bytes a certification signature covers.

    Version-tagged and newline-delimited so fields cannot run together and
    a signature over one payload shape can never be presented as a
    signature over another.
    """
    return "\n".join(
        (
            _CERTIFICATION_PAYLOAD_TAG,
            extension_id,
            version,
            package_sha256,
            manifest_sha256,
        )
    ).encode("utf-8")


def generate_signing_key_hex() -> str:
    """A fresh Ed25519 private seed as hex (for authors generating a key)."""
    Ed25519PrivateKey, _ = _require_cryptography()
    return str(Ed25519PrivateKey.generate().private_bytes_raw().hex())


def public_key_hex_from_seed(seed_hex: str) -> str:
    """The Ed25519 public key hex for a private seed hex."""
    Ed25519PrivateKey, _ = _require_cryptography()
    private = _private_key_from_seed(seed_hex, Ed25519PrivateKey)
    return str(private.public_key().public_bytes_raw().hex())


def _private_key_from_seed(seed_hex: str, Ed25519PrivateKey: type[Any]) -> Any:
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError as exc:
        raise SigningUnavailable(
            f"signing key must be 64 hex characters (a 32-byte Ed25519 seed), "
            f"got {len(seed_hex)} characters"
        ) from exc
    if len(seed) != 32:
        raise SigningUnavailable(
            f"signing key must decode to exactly 32 bytes (an Ed25519 seed), got {len(seed)}"
        )
    try:
        return Ed25519PrivateKey.from_private_bytes(seed)
    except Exception as exc:
        raise SigningUnavailable(f"signing key material is not usable: {exc}") from exc


def sign_payload(payload: bytes, signing_key_hex: str) -> tuple[str, str]:
    """Sign ``payload``; return ``(public_key_hex, signature_hex)``.

    Raises :class:`SigningUnavailable` when the ``cryptography`` package is
    missing or the key material is malformed — fail closed, with the fix in
    the message.
    """
    Ed25519PrivateKey, _ = _require_cryptography()
    key = _private_key_from_seed(signing_key_hex, Ed25519PrivateKey)
    signature = key.sign(payload)
    return key.public_key().public_bytes_raw().hex(), signature.hex()


def verify_payload(payload: bytes, signature_hex: str, public_key_hex: str) -> bool:
    """Verify a payload signature against a public key hex.

    Returns ``False`` — never raises — for malformed or non-verifying
    material: a verification failure is an answer, not a crash.
    """
    try:
        _, Ed25519PublicKey = _require_cryptography()
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(bytes.fromhex(signature_hex), payload)
    except Exception:
        return False
    return True


def sha256_hex(data: bytes) -> str:
    """Hex SHA-256 over exact bytes (the digest algorithm of record)."""
    return hashlib.sha256(data).hexdigest()
