"""Governed extension registry persistence (M9-B1, issue #939/#952).

Install records with publisher identity, package digest/signature metadata,
manifest snapshots, catalog provenance and durable trust evidence. The
inspect→authorize→install flow (#953) and the pin/upgrade/rollback lifecycle
(#954) build on these records; nothing here executes extension code.
"""

from maistro.extensions.sqlite_store import SqliteExtensionInstallStore
from maistro.extensions.store import (
    TRUST_POLICY,
    ActivationCallback,
    ExtensionInstallStore,
    InMemoryExtensionInstallStore,
)
from maistro.extensions.types import (
    DIGEST_ALGORITHM,
    ExtensionIdentityConflict,
    ExtensionRegistryError,
    InstallRecord,
    InstallRequest,
    ManifestSnapshot,
    PackageDigestMismatch,
    PackageIdentity,
    PackageSignatureInvalid,
    PublisherIdentity,
    PublisherKeyConflict,
    RegistryProvenance,
    TrustEvidence,
    UnknownPublisher,
    canonical_install_payload,
    identity_key,
    manifest_snapshot,
    sha256_hex,
)

__all__ = [
    "DIGEST_ALGORITHM",
    "TRUST_POLICY",
    "ActivationCallback",
    "ExtensionIdentityConflict",
    "ExtensionInstallStore",
    "ExtensionRegistryError",
    "InMemoryExtensionInstallStore",
    "InstallRecord",
    "InstallRequest",
    "ManifestSnapshot",
    "PackageDigestMismatch",
    "PackageIdentity",
    "PackageSignatureInvalid",
    "PublisherIdentity",
    "PublisherKeyConflict",
    "RegistryProvenance",
    "SqliteExtensionInstallStore",
    "TrustEvidence",
    "UnknownPublisher",
    "canonical_install_payload",
    "identity_key",
    "manifest_snapshot",
    "sha256_hex",
]
