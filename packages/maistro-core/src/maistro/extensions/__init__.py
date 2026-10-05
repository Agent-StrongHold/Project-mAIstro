"""Governed extension registry and activation flow (M9-B, issues #952/#953).

Public surface of the ``maistro.extensions`` package, in two layers:

- **M9-B1 registry (issue #952)**: immutable install records with publisher
  identity, package digest/signature metadata, manifest snapshots, catalog
  provenance and durable trust evidence; the append-only
  :class:`ExtensionInstallStore` protocol with its in-memory reference and
  SQLite durable twin. The inspect→authorize→install flow (#953) and the
  pin/upgrade/rollback lifecycle (#954) build on these records.
- **M9-B2 activation (issue #953)**: the governed install state machine —
  the pure evaluation modules (manifest, compatibility, trust, authority),
  the activation store seam, and :class:`ExtensionInstallService`. Nothing in
  this package ever imports extension code; activation runs only through the
  host-supplied :class:`ExtensionCodeLoader`, and only after explicit
  authorization.

Neither layer executes extension code: verification, evaluation and
authorization all operate on bytes and declarations alone.
"""

from __future__ import annotations

from maistro.extensions.authority import (
    AuthorityBaseline,
    AuthorityDelta,
    compute_authority_delta,
    normalize_permission,
)
from maistro.extensions.compatibility import (
    CompatibilityPolicy,
    CompatibilityReport,
    evaluate_compatibility,
)
from maistro.extensions.manifest import (
    SUPPORTED_MANIFEST_VERSION,
    assert_snapshot_intact,
    inspect_manifest,
    sha256_hex,
    verify_package_payload,
)
from maistro.extensions.service import (
    ExtensionCodeLoader,
    ExtensionInstallService,
    LoadedExtension,
    UnwiredExtensionLoader,
)
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore
from maistro.extensions.store import (
    TRUST_POLICY,
    ActivationCallback,
    ExtensionInstallStore,
    ExtensionStore,
    InMemoryExtensionInstallStore,
    InMemoryExtensionStore,
)
from maistro.extensions.trust import TrustPolicy, TrustReport, evaluate_trust
from maistro.extensions.types import (
    DIGEST_ALGORITHM,
    TERMINAL_STATES,
    TRANSITIONS,
    ArtifactMismatch,
    ExtensionDependency,
    ExtensionEntryPoint,
    ExtensionIdentityConflict,
    ExtensionInstallRecord,
    ExtensionLifecycleError,
    ExtensionManifest,
    ExtensionPackage,
    ExtensionRegistryError,
    ExtensionScope,
    ExtensionState,
    ExtensionTransition,
    InspectionConflict,
    InstallRecord,
    InstallRequest,
    InvalidTransition,
    ManifestRejected,
    ManifestSnapshot,
    PackageDigestMismatch,
    PackageIdentity,
    PackageSignatureInvalid,
    PublisherIdentity,
    PublisherKeyConflict,
    RegistryProvenance,
    TrustClaim,
    TrustEvidence,
    UnknownInstall,
    UnknownPublisher,
    canonical_install_payload,
    identity_key,
    manifest_snapshot,
)

__all__ = [
    "DIGEST_ALGORITHM",
    "SUPPORTED_MANIFEST_VERSION",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "TRUST_POLICY",
    "ActivationCallback",
    "ArtifactMismatch",
    "AuthorityBaseline",
    "AuthorityDelta",
    "CompatibilityPolicy",
    "CompatibilityReport",
    "ExtensionCodeLoader",
    "ExtensionDependency",
    "ExtensionEntryPoint",
    "ExtensionIdentityConflict",
    "ExtensionInstallRecord",
    "ExtensionInstallService",
    "ExtensionInstallStore",
    "ExtensionLifecycleError",
    "ExtensionManifest",
    "ExtensionPackage",
    "ExtensionRegistryError",
    "ExtensionScope",
    "ExtensionState",
    "ExtensionStore",
    "ExtensionTransition",
    "InMemoryExtensionInstallStore",
    "InMemoryExtensionStore",
    "InspectionConflict",
    "InstallRecord",
    "InstallRequest",
    "InvalidTransition",
    "LoadedExtension",
    "ManifestRejected",
    "ManifestSnapshot",
    "PackageDigestMismatch",
    "PackageIdentity",
    "PackageSignatureInvalid",
    "PublisherIdentity",
    "PublisherKeyConflict",
    "RegistryProvenance",
    "SqliteExtensionInstallStore",
    "TrustClaim",
    "TrustEvidence",
    "TrustPolicy",
    "TrustReport",
    "UnknownInstall",
    "UnknownPublisher",
    "UnwiredExtensionLoader",
    "assert_snapshot_intact",
    "canonical_install_payload",
    "compute_authority_delta",
    "evaluate_compatibility",
    "evaluate_trust",
    "identity_key",
    "inspect_manifest",
    "manifest_snapshot",
    "normalize_permission",
    "sha256_hex",
    "verify_package_payload",
]
