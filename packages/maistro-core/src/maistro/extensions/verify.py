"""Fail-closed package verification for extension installs (M9-B1, #952).

Both checks a package must pass *before* any of its code is imported, in the
order they can fail:

1. digest — the bytes in hand must digest to the identity's declared package
   digest (and the manifest body to the manifest digest), so what was
   downloaded is what the identity names;
2. signature — the publisher's signature over the canonical identity payload
   must verify against the *registered* publisher key, so the bytes are the
   ones the publisher signed.

Verification is a pure function of (identity, bytes, signature, key): no
network, no catalog, no mutable state. The store mints the resulting
:class:`~maistro.extensions.types.TrustEvidence` and persists it, so the
evidence outlives the key and the catalog it was checked against.

The Ed25519 check is deliberately self-contained here rather than reusing
``maistro.code_registry.verify``: that module is its own subsystem with its own
wiring story (SPEC-257), and tying this one to it would silently change the
reachability posture of two trees for the sake of ten lines.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature as _InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from maistro.extensions.types import (
    DIGEST_ALGORITHM,
    PackageDigestMismatch,
    PackageIdentity,
    PackageSignatureInvalid,
    canonical_install_payload,
    manifest_snapshot,
    sha256_hex,
)


def verify_package_bytes(identity: PackageIdentity, package_bytes: bytes) -> None:
    """Check the package bytes against the identity's declared digest.

    Raises :class:`PackageDigestMismatch` if the bytes are not what the
    identity names — a package altered in transit or on the catalog fails
    here, before the signature is even considered.
    """
    if sha256_hex(package_bytes) != identity.package_sha256:
        raise PackageDigestMismatch(
            f"package bytes do not digest to the declared {DIGEST_ALGORITHM} "
            f"digest for {identity.extension_name}@{identity.semantic_version}"
        )


def verify_package_signature(
    identity: PackageIdentity,
    manifest_body: str,
    signature: str,
    signing_public_key: str,
) -> None:
    """Verify the publisher signature over the canonical identity payload.

    ``signing_public_key`` is the key pinned on the *registered* publisher
    identity, not a key the request brought along — the registry's publisher
    record is the trust root. Raises :class:`PackageSignatureInvalid` when the
    presented manifest does not digest to the digest the signature covers,
    when the signature does not verify, or when the key/signature material is
    malformed; all three are fail-closed refusals, never a downgrade to
    unverified.
    """
    manifest = manifest_snapshot(manifest_body)
    if manifest.sha256 != identity.manifest_sha256:
        raise PackageSignatureInvalid(
            f"manifest does not digest to the digest the signature covers for "
            f"{identity.extension_name}@{identity.semantic_version}"
        )
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(signing_public_key))
        signature_bytes = bytes.fromhex(signature)
    except ValueError as exc:
        raise PackageSignatureInvalid(
            f"signature or key material is not valid hex for "
            f"{identity.extension_name}@{identity.semantic_version}"
        ) from exc
    try:
        public_key.verify(signature_bytes, canonical_install_payload(identity))
    except _InvalidSignature as exc:
        raise PackageSignatureInvalid(
            f"signature does not verify against the registered publisher key for "
            f"{identity.extension_name}@{identity.semantic_version}"
        ) from exc
