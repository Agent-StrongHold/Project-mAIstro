"""Fail-closed import of published catalog snapshots (catalog_json, #980).

The parser is the production consumer of an emitted ``catalog.json``. These
tests pin the refusals: a document that lies about its snapshot digest, an
entry whose identity contradicts its own manifest bytes, an unrecognized
format tag, and a signature that does not verify — each must raise rather
than hand a half-trusted catalog to resolution or the catalog service. The
happy path (real gallery publish → resolve_lock → CatalogService) is
exercised end to end in ``tests/test_reference_gallery.py``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from maistro.extensions.catalog_json import (
    CATALOG_FORMAT,
    CatalogDocumentError,
    canonical_json,
    parse_catalog_document,
    parse_catalog_json,
)
from maistro.extensions.types import (
    PackageIdentity,
    canonical_install_payload,
    sha256_hex,
)

PUBLISHER_ID = "pub-fixtures"

PACKAGE_SHA256 = "a" * 64

MANIFEST: dict[str, Any] = {
    "manifest_version": 1,
    "id": "acme.tool",
    "name": "Acme tool",
    "version": "1.0.0",
    "publisher": PUBLISHER_ID,
    "api_version": "1.0.0",
    "permissions": ["workspace.read"],
    "entry_points": [
        {"name": "main", "module": "acme_tool.plugin", "attribute": "PLUGIN"},
    ],
    "dependencies": [],
    "artifact": {"sha256": PACKAGE_SHA256, "size": 2048},
}


def _identity(manifest_bytes: bytes) -> PackageIdentity:
    return PackageIdentity(
        extension_name=str(MANIFEST["id"]),
        semantic_version=str(MANIFEST["version"]),
        package_sha256=PACKAGE_SHA256,
        manifest_sha256=sha256_hex(manifest_bytes),
    )


def _public_key_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def _document(signer: Ed25519PrivateKey, *, public_key: str | None = None) -> dict[str, Any]:
    """One well-formed single-entry catalog document, signed for real."""
    manifest_bytes = canonical_json(MANIFEST)
    identity = _identity(manifest_bytes)
    entry = {
        "identity": {
            "extension_name": identity.extension_name,
            "semantic_version": identity.semantic_version,
            "package_sha256": identity.package_sha256,
            "manifest_sha256": identity.manifest_sha256,
        },
        "source": "fixtures:catalog",
        "publisher_id": PUBLISHER_ID,
        "signature": signer.sign(canonical_install_payload(identity)).hex(),
        "dependencies": [],
        "manifest": MANIFEST,
        "manifest_bytes": manifest_bytes.decode("utf-8"),
        "artifact_file": "artifacts/acme_tool-1.0.0-py3-none-any.whl",
    }
    snapshot = {
        "format": CATALOG_FORMAT,
        "publisher": PUBLISHER_ID,
        "signing_public_key": public_key if public_key is not None else _public_key_hex(signer),
        "entries": [entry],
    }
    return {
        **snapshot,
        "catalog_snapshot_sha256": sha256_hex(canonical_json(snapshot)),
    }


@pytest.fixture()
def signer() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _reseal(document: dict[str, Any]) -> dict[str, Any]:
    """Recompute the snapshot digest after a test mutation, so the deeper
    per-entry checks are reached instead of the digest refusal."""
    document["catalog_snapshot_sha256"] = sha256_hex(
        canonical_json({k: v for k, v in document.items() if k != "catalog_snapshot_sha256"})
    )
    return document


def test_well_formed_document_parses_into_platform_objects(
    signer: Ed25519PrivateKey,
) -> None:
    """The document imports into the exact objects resolution and the
    catalog service consume, with the verified snapshot digest attached."""
    parsed = parse_catalog_document(_document(signer))
    assert parsed.snapshot_sha256
    (entry,) = parsed.entries
    assert entry.identity.extension_name == "acme.tool"
    assert entry.catalog_snapshot_sha256 == parsed.snapshot_sha256
    assert parsed.manifests[entry.identity].extension_id == "acme.tool"
    assert parsed.catalog().entries == (entry,)
    # The (entry, manifest) pairs ``CatalogStore.set_catalog`` consumes,
    # composed straight off the parsed fields — nothing reconstructed.
    pairs = tuple((e, parsed.manifests[e.identity]) for e in parsed.entries)
    assert pairs == ((entry, parsed.manifests[entry.identity]),)


def test_refuses_a_document_whose_snapshot_digest_covers_something_else(
    signer: Ed25519PrivateKey,
) -> None:
    """An entry edited after signing (or a digest copied from another
    revision) cannot pass: the claimed digest must cover exactly the
    entries shipped."""
    document = _document(signer)
    document["entries"][0]["publisher_id"] = "someone-else"
    with pytest.raises(CatalogDocumentError, match="snapshot digest mismatch"):
        parse_catalog_json(json.dumps(document))


def test_refuses_an_identity_that_contradicts_its_manifest(
    signer: Ed25519PrivateKey,
) -> None:
    """The identity's package digest must agree with the manifest's artifact
    claim — otherwise the manifest bytes are not what the identity was
    published from, and the entry is refused before resolution sees it."""
    document = _document(signer)
    document["entries"][0]["identity"]["package_sha256"] = "b" * 64
    with pytest.raises(CatalogDocumentError, match="artifact claim"):
        parse_catalog_json(json.dumps(_reseal(document)))


def test_refuses_an_unrecognized_format(signer: Ed25519PrivateKey) -> None:
    document = _document(signer)
    document["format"] = "maistro-extension-catalog:v2"
    with pytest.raises(CatalogDocumentError, match="unsupported catalog format"):
        parse_catalog_json(json.dumps(document))


def test_refuses_a_signature_that_does_not_verify(signer: Ed25519PrivateKey) -> None:
    """Self-consistency is still checked: a signature over a different
    payload fails against the document's own publishing key."""
    document = _document(signer)
    document["entries"][0]["signature"] = signer.sign(b"unrelated payload").hex()
    with pytest.raises(CatalogDocumentError, match="does not verify"):
        parse_catalog_json(json.dumps(_reseal(document)))


def test_refuses_a_signature_keyed_to_a_different_key(signer: Ed25519PrivateKey) -> None:
    """A key swap without re-signing is incoherent and refused."""
    other = Ed25519PrivateKey.generate()
    document = _document(signer, public_key=_public_key_hex(other))
    with pytest.raises(CatalogDocumentError, match="does not verify"):
        parse_catalog_json(json.dumps(document))


def test_refuses_duplicate_identities(signer: Ed25519PrivateKey) -> None:
    document = _document(signer)
    document["entries"].append(json.loads(json.dumps(document["entries"][0])))
    with pytest.raises(CatalogDocumentError, match="twice"):
        parse_catalog_json(json.dumps(_reseal(document)))
