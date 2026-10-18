"""Shared signing fixtures for the extension install-record suites (M9-B1).

Real Ed25519 keys via ``cryptography`` — the same primitive
``code_registry.verify.Ed25519Verifier`` verifies with — so every rule these
suites pin is exercised against actual signatures, not a stubbed verifier.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from maistro.extensions.resolution import CatalogEntry, ExtensionDependency
from maistro.extensions.types import (
    InstallRequest,
    PackageIdentity,
    PublisherIdentity,
    RegistryProvenance,
    canonical_install_payload,
    manifest_snapshot,
    sha256_hex,
)

MANIFEST_BODY = """\
name: ext-tool
version: 1.0.0
description: A governed extension used by the M9-B1 suites.
entry: main.py
"""

PACKAGE_BYTES = b"extension package payload\n"

REGISTERED_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
RETRIEVED_AT = datetime(2026, 9, 2, 8, 30, 0, tzinfo=UTC)

CATALOG_URL = "https://catalog.example/org/extensions.json"
CATALOG_SNAPSHOT = "f" * 64


def public_key_hex(key: Ed25519PrivateKey) -> str:
    """Raw Ed25519 public key, hex-encoded (the store's key material form)."""
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return raw.hex()


def key_fingerprint(key: Ed25519PrivateKey) -> str:
    """The digest form records and operators compare."""
    return hashlib.sha256(bytes.fromhex(public_key_hex(key))).hexdigest()


def make_publisher(
    publisher_id: str = "pub-1",
    signer: Ed25519PrivateKey | None = None,
    display_name: str = "Example Publisher",
) -> tuple[PublisherIdentity, Ed25519PrivateKey]:
    """A publisher identity pinned to a freshly generated key."""
    signing_key = signer if signer is not None else Ed25519PrivateKey.generate()
    publisher = PublisherIdentity(
        publisher_id=publisher_id,
        display_name=display_name,
        signing_key_fingerprint=key_fingerprint(signing_key),
        signing_public_key=public_key_hex(signing_key),
        registered_at=REGISTERED_AT,
    )
    return publisher, signing_key


def make_identity(
    *,
    package_bytes: bytes = PACKAGE_BYTES,
    manifest_body: str = MANIFEST_BODY,
    name: str = "ext-tool",
    version: str = "1.0.0",
) -> PackageIdentity:
    """The installed-version identity for the given bytes and manifest."""
    return PackageIdentity(
        extension_name=name,
        semantic_version=version,
        package_sha256=sha256_hex(package_bytes),
        manifest_sha256=manifest_snapshot(manifest_body).sha256,
    )


def sign(key: Ed25519PrivateKey, identity: PackageIdentity) -> str:
    """The publisher signature over the canonical identity payload."""
    return key.sign(canonical_install_payload(identity)).hex()


def make_request(
    identity: PackageIdentity,
    signature: str,
    *,
    publisher_id: str = "pub-1",
    manifest_body: str = MANIFEST_BODY,
    catalog_url: str = CATALOG_URL,
) -> InstallRequest:
    """An install request carrying one catalog's provenance."""
    return InstallRequest(
        identity=identity,
        publisher_id=publisher_id,
        signature=signature,
        manifest_body=manifest_body,
        provenance=RegistryProvenance(
            catalog_url=catalog_url,
            catalog_snapshot_sha256=CATALOG_SNAPSHOT,
            retrieved_at=RETRIEVED_AT,
        ),
    )


def install_bundle(
    *,
    name: str = "ext-tool",
    version: str = "1.0.0",
    package_bytes: bytes = PACKAGE_BYTES,
    manifest_body: str = MANIFEST_BODY,
    publisher_id: str = "pub-1",
    signer: Ed25519PrivateKey | None = None,
    catalog_url: str = CATALOG_URL,
) -> dict[str, Any]:
    """A coherent publisher + identity + signature + request bundle."""
    publisher, signing_key = make_publisher(publisher_id=publisher_id, signer=signer)
    identity = make_identity(
        package_bytes=package_bytes, manifest_body=manifest_body, name=name, version=version
    )
    request = make_request(
        identity,
        sign(signing_key, identity),
        publisher_id=publisher_id,
        manifest_body=manifest_body,
        catalog_url=catalog_url,
    )
    return {
        "publisher": publisher,
        "key": signing_key,
        "identity": identity,
        "request": request,
        "package_bytes": package_bytes,
        "manifest_body": manifest_body,
    }


def reidentify(identity: PackageIdentity, **changes: Any) -> PackageIdentity:
    """A copy of ``identity`` with fields replaced (test-legibility helper)."""
    return replace(identity, **changes)


def catalog_entry(
    bundle: dict[str, Any],
    *,
    source: str = CATALOG_URL,
    snapshot: str = CATALOG_SNAPSHOT,
    dependencies: tuple[ExtensionDependency, ...] = (),
) -> CatalogEntry:
    """The catalog offering of one bundle: identity, source, and signature.

    The signature is the bundle's publisher key signing the identity — the
    exact bytes an install verifies at materialization time — so a catalog
    entry built here round-trips through the real store unchanged.
    """
    identity = bundle["identity"]
    return CatalogEntry(
        identity=identity,
        source=source,
        catalog_snapshot_sha256=snapshot,
        publisher_id=bundle["publisher"].publisher_id,
        signature=sign(bundle["key"], identity),
        dependencies=dependencies,
    )
