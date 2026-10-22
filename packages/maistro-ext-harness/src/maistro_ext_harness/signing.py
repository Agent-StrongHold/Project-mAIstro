"""Digest/signing helpers for certification (M9-H3, #975).

The certification signature is an **Ed25519 signature over a canonical,
version-tagged payload covering the report's complete evidence** —
identity, artifact digests, executed checks, conformance results, and the
decision (`canonical_evidence_payload`). Two payloads are recorded:

- the **evidence payload** (what the signature actually authenticates):
    maistro-extension-certification-evidence:v1
    <the report's full content minus the signature block, canonical JSON>

  so a signature authenticates the verdict as much as the bytes: flipping
  ``certified``, clearing a decline reason, or whitewashing a failed check
  changes the signed content and the signature stops verifying;

- the **identity payload** (what a registry checks first, because it
  parallels the canonical install payload the product-side installer
  verifies — `maistro.extensions.verify`, M9-B1; the same identity triple,
  the same digest algorithm, a version tag that makes replay of one
  format as the other impossible):
    maistro-extension-certification:v1
    <extension id>
    <extension version>
    <package sha256>
    <manifest sha256>

A registry can therefore later ingest a certification as *evidence*
without this package becoming a dependency of the product, and never as
*authorization*: the report itself says the consuming lifecycle must
still run its own policy.

`cryptography` is an optional dependency (the ``signing`` extra): the
harness's default runtime stays standard-library only, and a signing
request without the extra fails **closed** with an actionable error,
never with a downgrade to "unsigned but claims signed". The same
exception on the verification path is *not* a verification failure —
`verify_payload` re-raises `SigningUnavailable` so callers can say
"install the signing extra to check this signature" instead of the
misleading "signature does not verify".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

__all__ = [
    "DIGEST_ALGORITHM",
    "SIGNING_EXTRA",
    "SigningUnavailable",
    "canonical_certification_payload",
    "canonical_evidence_payload",
    "generate_signing_key_hex",
    "public_key_hex_from_seed",
    "sign_payload",
    "verify_payload",
]

DIGEST_ALGORITHM = "sha256"

#: The pip extra that carries the signing implementation.
SIGNING_EXTRA = "signing"

_CERTIFICATION_PAYLOAD_TAG = "maistro-extension-certification:v1"

#: The tag of the report-content payload a certification signature actually
#: authenticates: identity, digests, checks, conformance evidence, decision.
_CERTIFICATION_EVIDENCE_TAG = "maistro-extension-certification-evidence:v1"


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
    """The installer-parallel identity payload: extension id, version, and
    the two digests that bind the report to bytes.

    Version-tagged and newline-delimited so fields cannot run together and
    a signature over one payload shape can never be presented as a
    signature over another. The Ed25519 signature itself covers the larger
    `canonical_evidence_payload` (which includes these fields' source
    records); this payload is recorded alongside it because a registry
    ingesting a certification checks this exact identity binding first.
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


def canonical_evidence_payload(report: Mapping[str, Any]) -> bytes:
    """The exact bytes a certification signature authenticates: the whole
    report — identity, artifact digests, executed checks, conformance
    evidence, environment, and the decision — minus the report's own
    ``signature`` block.

    Deterministic by construction (sorted keys, fixed separators, UTF-8),
    so the same report content yields the same bytes at signing time and
    at every later verification, across processes and hosts: a consumer
    re-derives these bytes from the report it holds, and the Ed25519
    signature either verifies over exactly that content or it does not.
    Any edit after signing — a flipped ``certified`` verdict, a cleared
    decline reason, a whitewashed check — changes the bytes and breaks
    the signature.

    Raises ``TypeError``/``ValueError`` when the content is not JSON
    canonicalizable (callers treat that as “nothing was signed” or “the
    report cannot be authenticated”, never as a crash).
    """
    evidence = {key: value for key, value in report.items() if key != "signature"}
    document = json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return f"{_CERTIFICATION_EVIDENCE_TAG}\n{document}".encode()


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
    material: a verification failure is an answer, not a crash. The one
    exception is :class:`SigningUnavailable`: an absent verification
    backend is *not* a verification failure, and folding it into ``False``
    would tell the user a valid signature “does not verify” when what
    actually happened is the harness lacks the ``cryptography`` package
    to check it. Callers surface that as its own actionable outcome.
    """
    try:
        _, Ed25519PublicKey = _require_cryptography()
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(bytes.fromhex(signature_hex), payload)
    except SigningUnavailable:
        raise
    except Exception:
        return False
    return True


def sha256_hex(data: bytes) -> str:
    """Hex SHA-256 over exact bytes (the digest algorithm of record)."""
    return hashlib.sha256(data).hexdigest()
