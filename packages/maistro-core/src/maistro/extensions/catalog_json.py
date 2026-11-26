"""Production import of a published catalog snapshot (M9-J2, #980).

The publishing side (e.g. ``extensions/reference-gallery/tools/publish.py``)
emits ``catalog.json``: one entry per package — identity, publisher, Ed25519
signature, declared dependencies, final manifest bytes — plus the publishing
public key and a snapshot digest over the canonical entry set. This module is
the consumer half of that contract: it turns such a document into the exact
platform objects the rest of ``maistro.extensions`` operates on, so an
operator can feed the published artifact straight into dependency resolution
(:func:`~maistro.extensions.resolution.resolve_lock`) and the catalog service
(:meth:`~maistro.extensions.catalog_service.CatalogStore.set_catalog`)
without reconstructing anything by hand.

What the parser checks, in the order a consumer can know them:

1. **Format** — the ``format`` tag must be ``CATALOG_FORMAT``; unknown
   documents are refused rather than guessed at.
2. **Snapshot digest** — the claimed ``catalog_snapshot_sha256`` must equal
   the SHA-256 of the canonical JSON of the snapshot it accompanies. The
   digest covers exactly the entries shipped, so an entry edited in place
   (or a digest copied from another revision) fails here.
3. **Per-entry integrity** — each entry's manifest bytes must inspect
   cleanly, the identity must agree with those bytes (name, version,
   manifest digest, artifact digest), and the entry's signature must verify
   against the publishing key the document itself carries.

The signature check in step 3 is *internal consistency*: it proves the
document hangs together, not that the publisher is trusted — trust comes
from the key registered on the publisher record, which install-time
verification (:func:`~maistro.extensions.verify.verify_package_signature`)
checks against. Likewise the artifact digest names wheel bytes this document
does not carry; a consumer fetches the artifact and re-verifies both digests
and signature through the install lifecycle. Nothing here imports extension
code or grants authority: the output is metadata plus inspected manifest
snapshots, the same inputs a registry operator would have assembled by hand.

Canonicalization note: the snapshot digest is computed over sorted-key,
whitespace-free UTF-8 JSON — byte-identical to the publisher's
``canonical_json``. Both sides must canonicalize identically or no digest
can ever agree; the mirrored definition is version-tagged via the format
string.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from maistro.extensions.manifest import inspect_manifest, sha256_hex
from maistro.extensions.resolution import CatalogEntry, ExtensionCatalog, ExtensionDependency
from maistro.extensions.types import (
    ExtensionManifest,
    ExtensionRegistryError,
    PackageIdentity,
    PackageSignatureInvalid,
)
from maistro.extensions.verify import verify_package_signature

#: Version tag of the catalog serialization. Bumping it is a format change:
#: :func:`parse_catalog_document` refuses anything else rather than guessing.
CATALOG_FORMAT = "maistro-extension-catalog:v1"

#: The document key carrying the snapshot digest; it is excluded from the
#: bytes the digest itself covers.
_SNAPSHOT_DIGEST_KEY = "catalog_snapshot_sha256"

_REQUIRED_ENTRY_KEYS = (
    "identity",
    "source",
    "publisher_id",
    "signature",
    "dependencies",
    "manifest_bytes",
)


class CatalogDocumentError(ExtensionRegistryError):
    """A published catalog document is malformed, inconsistent, or unknown.

    Raised for shape errors, an unrecognized format tag, a snapshot digest
    that does not cover the shipped entries, an entry whose identity
    contradicts its own manifest bytes, or duplicate identities. Every case
    is a fail-closed refusal: a catalog that cannot prove its own coherence
    is never handed to resolution or the catalog service.
    """


@dataclass(frozen=True)
class ParsedCatalogSnapshot:
    """A published catalog, as the platform's machinery consumes it.

    ``entries`` feeds :func:`~maistro.extensions.resolution.resolve_lock`
    (or ``ExtensionCatalog(entries)`` directly); the ``(entry, manifest)``
    pairs its ``entries``/``manifests`` fields compose feed
    ``CatalogStore.set_catalog``. ``snapshot_sha256`` is the verified digest
    every resolved lock entry records as its catalog provenance.
    """

    format: str
    publisher: str
    signing_public_key: str
    snapshot_sha256: str
    entries: tuple[CatalogEntry, ...]
    manifests: Mapping[PackageIdentity, ExtensionManifest]
    #: The artifact reference each entry ships (e.g. ``artifacts/foo.whl``),
    #: relative to the catalog document — what a consumer fetches before
    #: handing the bytes to digest verification.
    artifact_files: Mapping[PackageIdentity, str]

    def catalog(self) -> ExtensionCatalog:
        """The immutable snapshot dependency resolution runs against."""
        return ExtensionCatalog(entries=self.entries)


def canonical_json(obj: object) -> bytes:
    """The one JSON serialization every catalog digest is computed over.

    Sorted keys, no whitespace, UTF-8 — byte-identical to the publisher's
    ``canonical_json``; the snapshot digest only means anything because both
    sides canonicalize the same way.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def parse_catalog_json(text: str) -> ParsedCatalogSnapshot:
    """Parse a published ``catalog.json`` document from its text."""
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CatalogDocumentError(f"catalog document is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise CatalogDocumentError("catalog document must be a JSON object")
    return parse_catalog_document(document)


def parse_catalog_document(document: Mapping[str, Any]) -> ParsedCatalogSnapshot:
    """Import a published catalog document into platform objects.

    Fails closed on every way a document can lie about itself (see the
    module docstring); on success the result is exactly the input a registry
    operator would have had to reconstruct field by field.
    """
    fmt = document.get("format")
    if fmt != CATALOG_FORMAT:
        raise CatalogDocumentError(
            f"unsupported catalog format {fmt!r}; this consumer speaks {CATALOG_FORMAT!r}"
        )

    claimed_digest = document.get(_SNAPSHOT_DIGEST_KEY)
    if not isinstance(claimed_digest, str):
        raise CatalogDocumentError(f"catalog document carries no {_SNAPSHOT_DIGEST_KEY}")
    snapshot = {key: value for key, value in document.items() if key != _SNAPSHOT_DIGEST_KEY}
    snapshot_sha256 = sha256_hex(canonical_json(snapshot))
    if snapshot_sha256 != claimed_digest:
        raise CatalogDocumentError(
            "catalog snapshot digest mismatch: the claimed "
            f"{_SNAPSHOT_DIGEST_KEY} does not cover the entries shipped "
            f"(computed {snapshot_sha256}, claimed {claimed_digest})"
        )

    publisher = _string_field(document, "publisher", "catalog document")
    signing_public_key = _string_field(document, "signing_public_key", "catalog document")
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise CatalogDocumentError("catalog document carries no entries")

    entries, manifests, artifact_files = _parse_entries(
        raw_entries, signing_public_key, snapshot_sha256
    )
    return ParsedCatalogSnapshot(
        format=CATALOG_FORMAT,
        publisher=publisher,
        signing_public_key=signing_public_key,
        snapshot_sha256=snapshot_sha256,
        entries=entries,
        manifests=manifests,
        artifact_files=artifact_files,
    )


def _parse_entries(
    raw_entries: list[Any],
    signing_public_key: str,
    snapshot_sha256: str,
) -> tuple[
    tuple[CatalogEntry, ...],
    dict[PackageIdentity, ExtensionManifest],
    dict[PackageIdentity, str],
]:
    """Every entry in one pass, refusing duplicate identities.

    Split from :func:`parse_catalog_document` so each function stays a
    single readable decision chain; the refusal semantics are unchanged.
    """
    entries: list[CatalogEntry] = []
    manifests: dict[PackageIdentity, ExtensionManifest] = {}
    artifact_files: dict[PackageIdentity, str] = {}
    seen: set[PackageIdentity] = set()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise CatalogDocumentError(f"catalog entry #{index} must be a JSON object")
        entry = _parse_entry(raw, index, signing_public_key, snapshot_sha256)
        if entry.identity in seen:
            raise CatalogDocumentError(
                f"catalog lists {entry.identity.extension_name} "
                f"{entry.identity.semantic_version} twice"
            )
        seen.add(entry.identity)
        entries.append(entry)
        manifests[entry.identity] = inspect_manifest(str(raw["manifest_bytes"]).encode("utf-8"))
        artifact_files[entry.identity] = _string_field(
            raw, "artifact_file", f"catalog entry #{index}"
        )
    return tuple(entries), manifests, artifact_files


def _parse_entry(
    raw: Mapping[str, Any],
    index: int,
    signing_public_key: str,
    snapshot_sha256: str,
) -> CatalogEntry:
    """One catalog entry: identity, signature, dependencies, manifest.

    The manifest is inspected (never trusted as parsed JSON) and every
    identity field is cross-checked against it, so the entry, the manifest
    bytes, and the signed payload cannot disagree without the refusal naming
    which one lied.
    """
    label = f"catalog entry #{index}"
    missing = [key for key in _REQUIRED_ENTRY_KEYS if key not in raw]
    if missing:
        raise CatalogDocumentError(f"{label} is missing required keys: {', '.join(missing)}")

    identity = _parse_identity(raw["identity"], label)
    publisher_id = _string_field(raw, "publisher_id", label)
    source = _string_field(raw, "source", label)
    signature = _string_field(raw, "signature", label)
    manifest_body = raw["manifest_bytes"]
    if not isinstance(manifest_body, str):
        raise CatalogDocumentError(f"{label} manifest_bytes must be a JSON string")

    manifest = inspect_manifest(manifest_body.encode("utf-8"))
    if manifest.extension_id != identity.extension_name:
        raise CatalogDocumentError(
            f"{label} identity names {identity.extension_name!r} but its manifest "
            f"declares extension id {manifest.extension_id!r}"
        )
    if manifest.version != identity.semantic_version:
        raise CatalogDocumentError(
            f"{label} identity pins version {identity.semantic_version} but its "
            f"manifest declares {manifest.version}"
        )
    if sha256_hex(manifest_body.encode("utf-8")) != identity.manifest_sha256:
        raise CatalogDocumentError(
            f"{label} manifest bytes do not digest to the identity's manifest_sha256"
        )
    if manifest.artifact_sha256 != identity.package_sha256:
        raise CatalogDocumentError(
            f"{label} identity's package digest contradicts the manifest's "
            "artifact claim (the manifest cannot be the bytes this identity was "
            "published from)"
        )
    try:
        verify_package_signature(identity, manifest_body, signature, signing_public_key)
    except PackageSignatureInvalid as exc:
        raise CatalogDocumentError(
            f"{label} signature does not verify against the document's own publishing key: {exc}"
        ) from exc

    return CatalogEntry(
        identity=identity,
        source=source,
        catalog_snapshot_sha256=snapshot_sha256,
        publisher_id=publisher_id,
        signature=signature,
        dependencies=_parse_dependencies(raw["dependencies"], label),
    )


def _parse_identity(raw: object, label: str) -> PackageIdentity:
    """Reconstruct one package identity from its published fields."""
    if not isinstance(raw, dict):
        raise CatalogDocumentError(f"{label} identity must be a JSON object")
    fields = ("extension_name", "semantic_version", "package_sha256", "manifest_sha256")
    missing = [field for field in fields if field not in raw]
    if missing:
        raise CatalogDocumentError(f"{label} identity is missing: {', '.join(missing)}")
    identity = PackageIdentity(
        extension_name=_string_field(raw, "extension_name", f"{label} identity"),
        semantic_version=_string_field(raw, "semantic_version", f"{label} identity"),
        package_sha256=_string_field(raw, "package_sha256", f"{label} identity"),
        manifest_sha256=_string_field(raw, "manifest_sha256", f"{label} identity"),
    )
    for digest_field in ("package_sha256", "manifest_sha256"):
        value = getattr(identity, digest_field)
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise CatalogDocumentError(
                f"{label} identity {digest_field} is not a lowercase hex sha256"
            )
    return identity


def _parse_dependencies(raw: object, label: str) -> tuple[ExtensionDependency, ...]:
    """Reconstruct the declared dependency edges in resolution's form."""
    if not isinstance(raw, list):
        raise CatalogDocumentError(f"{label} dependencies must be a JSON array")
    dependencies: list[ExtensionDependency] = []
    for dep in raw:
        if not isinstance(dep, dict):
            raise CatalogDocumentError(f"{label} dependency must be a JSON object")
        dependencies.append(
            ExtensionDependency(
                target=_string_field(dep, "target", f"{label} dependency"),
                range_text=_string_field(dep, "range_text", f"{label} dependency"),
                required=bool(dep.get("required", True)),
            )
        )
    return tuple(dependencies)


def _string_field(raw: Mapping[str, Any], key: str, label: str) -> str:
    """Read one required non-empty string field, failing closed."""
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise CatalogDocumentError(f"{label} field {key!r} must be a non-empty string")
    return value
