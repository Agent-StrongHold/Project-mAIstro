"""Record model for the governed extension registry (M9-B1, issue #952).

Everything here is an immutable fact about *what was installed*, not about the
mutable catalog it was discovered in. The registry's catalog metadata (prices,
descriptions, trust claims, even the catalog itself) can change or disappear at
any time; an install record may not. That is why a record snapshots:

* the publisher identity as it was at install time (not a foreign key into a
  mutable publisher table);
* the exact manifest bytes installed;
* the registry/catalog provenance the package was fetched from;
* the signature/trust verification result and its timestamp, minted at
  verification time and durably stored — never recomputed on read.

The installed-version identity is :class:`PackageIdentity`: extension name,
semantic version, package digest, and manifest digest together. Two packages
that share a semantic version but differ in digest are *different identities*;
the stores refuse to let the second one silently masquerade as the first.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

#: The one digest algorithm install records use. Pinned by name so a record
#: can always state what its hex digests are digests *of*.
DIGEST_ALGORITHM = "sha256"


class ExtensionRegistryError(RuntimeError):
    """Base class for extension registry/install-record failures."""


class UnknownPublisher(ExtensionRegistryError):
    """An install names a publisher the registry has no identity record for."""


class PublisherKeyConflict(ExtensionRegistryError):
    """A publisher identity would be re-registered under a different key.

    A publisher's signing key is pinned at first registration. Re-registering
    the same publisher id under a different key is exactly the move a registry
    compromise would make, so it fails closed; key rotation is a lifecycle
    concern with its own auditable flow, not a silent overwrite.
    """


class PackageDigestMismatch(ExtensionRegistryError):
    """The bytes in hand do not digest to the identity's declared digest."""


class PackageSignatureInvalid(ExtensionRegistryError):
    """The signature does not verify against the registered publisher key."""


class ExtensionIdentityConflict(ExtensionRegistryError):
    """A package reuses an installed (name, version) under different bytes."""


def sha256_hex(data: bytes) -> str:
    """Hex sha256 of ``data`` — the digest form every record field uses."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class PublisherIdentity:
    """Who published an extension, pinned at first registration.

    ``signing_public_key`` is the raw Ed25519 public key, hex-encoded; it is
    the trust root install-time verification runs against.
    ``signing_key_fingerprint`` is the digest of that key, the short form
    records and operators compare.
    """

    publisher_id: str
    display_name: str
    signing_key_fingerprint: str
    signing_public_key: str
    registered_at: datetime


@dataclass(frozen=True)
class PackageIdentity:
    """The immutable identity of one installed extension version.

    A semantic version alone does not name a package: the same
    ``(extension_name, semantic_version)`` must always carry the same package
    and manifest digests. Anything else is a different identity, and the
    stores treat it as a conflict rather than a replacement.
    """

    extension_name: str
    semantic_version: str
    package_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class ManifestSnapshot:
    """The exact manifest bytes an install was made from."""

    body: str
    sha256: str


def manifest_snapshot(body: str) -> ManifestSnapshot:
    """Snapshot manifest ``body``, digesting it at snapshot time."""
    return ManifestSnapshot(body=body, sha256=sha256_hex(body.encode()))


@dataclass(frozen=True)
class RegistryProvenance:
    """Where the installed package was discovered and fetched from.

    Recorded once, at install time: if the catalog later rewrites or deletes
    the entry, the record still says what the registry source claimed when the
    bytes were pulled.
    """

    catalog_url: str
    catalog_snapshot_sha256: str
    retrieved_at: datetime


@dataclass(frozen=True)
class TrustEvidence:
    """The durable result of signature/trust verification.

    Minted by the store when an install is recorded and stored with it. Reads
    never re-verify: the evidence is the audit trail of the check that already
    happened, so it stays queryable even when the signing key or catalog that
    produced it is long gone.
    """

    verified: bool
    verifier_key_fingerprint: str
    policy: str
    subject_sha256: str
    verified_at: datetime


@dataclass(frozen=True)
class InstallRequest:
    """Everything the caller supplies to record one install.

    ``package_bytes`` is passed to :meth:`record_install` separately (it is
    the bytes being verified, not record metadata). The signature is over
    :func:`canonical_install_payload` — the canonical identity string — made
    with the registered publisher's key.
    """

    identity: PackageIdentity
    publisher_id: str
    signature: str
    manifest_body: str
    provenance: RegistryProvenance


@dataclass(frozen=True)
class InstallRecord:
    """One immutable installed-version record, and the whole audit trail."""

    install_id: str
    identity: PackageIdentity
    publisher: PublisherIdentity
    signature: str
    manifest: ManifestSnapshot
    provenance: RegistryProvenance
    evidence: TrustEvidence
    installed_at: datetime


def canonical_install_payload(identity: PackageIdentity) -> bytes:
    """The exact bytes a publisher signs for one package identity.

    Version-tagged and newline-delimited so fields cannot run together and an
    old signature can never be replayed as a new format.
    """
    return "\n".join(
        (
            "maistro-extension-install:v1",
            identity.extension_name,
            identity.semantic_version,
            identity.package_sha256,
            identity.manifest_sha256,
        )
    ).encode()


def identity_key(identity: PackageIdentity) -> tuple[str, str, str, str]:
    """Hashable key for the full installed-version identity."""
    return (
        identity.extension_name,
        identity.semantic_version,
        identity.package_sha256,
        identity.manifest_sha256,
    )


def _payload_object(record: InstallRecord) -> dict[str, Any]:
    """JSON-safe dict of one record, with datetimes as ISO-8601 strings."""
    payload = asdict(record)
    payload["publisher"]["registered_at"] = record.publisher.registered_at.isoformat()
    payload["provenance"]["retrieved_at"] = record.provenance.retrieved_at.isoformat()
    payload["evidence"]["verified_at"] = record.evidence.verified_at.isoformat()
    payload["installed_at"] = record.installed_at.isoformat()
    return payload


def _datetime_value(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def record_to_json(record: InstallRecord) -> str:
    """Serialize one install record for the durable payload column."""
    return json.dumps(_payload_object(record), sort_keys=True)


def publisher_to_json(publisher: PublisherIdentity) -> str:
    """Serialize a publisher identity for the durable payload column."""
    payload = asdict(publisher)
    payload["registered_at"] = publisher.registered_at.isoformat()
    return json.dumps(payload, sort_keys=True)


def publisher_from_json(raw: str) -> PublisherIdentity:
    """Rebuild a publisher identity from its durable payload."""
    payload = json.loads(raw)
    payload["registered_at"] = _datetime_value(payload["registered_at"])
    return PublisherIdentity(**payload)


def record_from_json(raw: str) -> InstallRecord:
    """Rebuild a record from its durable payload.

    Datetimes are restored timezone-aware (naive values are read as UTC), so
    a record round-trips equal to what was written.
    """

    def build(value: dict[str, Any], cls: type) -> Any:
        fields = dict(value)
        if cls is PublisherIdentity:
            fields["registered_at"] = _datetime_value(fields["registered_at"])
        elif cls is RegistryProvenance:
            fields["retrieved_at"] = _datetime_value(fields["retrieved_at"])
        elif cls is TrustEvidence:
            fields["verified_at"] = _datetime_value(fields["verified_at"])
        return cls(**fields)

    payload = json.loads(raw)
    return InstallRecord(
        install_id=str(payload["install_id"]),
        identity=PackageIdentity(**payload["identity"]),
        publisher=build(payload["publisher"], PublisherIdentity),
        signature=str(payload["signature"]),
        manifest=ManifestSnapshot(**payload["manifest"]),
        provenance=build(payload["provenance"], RegistryProvenance),
        evidence=build(payload["evidence"], TrustEvidence),
        installed_at=_datetime_value(payload["installed_at"]),
    )
