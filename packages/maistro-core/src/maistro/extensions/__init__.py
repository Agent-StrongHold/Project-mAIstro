"""Governed extension registry, activation flow, and dependency resolution
(M9-B/M9-C, issues #952/#953/#956).

Public surface of the ``maistro.extensions`` package, in three layers:

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
- **M9-C2 resolution (issue #956)**: strict semantic-version ranges
  (``semver``), a deterministic resolver producing a reproducible
  :class:`LockState` (``resolution``), and lock-driven reinstall through the
  install store (:func:`materialize_lock`).
- **M9-I2 metering (issue #977)**: usage attribution and Workspace/org quota
  enforcement at the extension seam (``metering``) — physical usage recorded
  once against canonical Invocation ids, nested delegation lineage, atomic
  reservation/refund/correction semantics, and aggregation by Workspace,
  extension, publisher, capability and time window. Attribution only: the
  canonical provider totals stay with ``maistro.quota``.

No layer executes extension code: verification, evaluation, authorization,
resolution and metering all operate on declarations, identity and amounts
alone.
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
from maistro.extensions.metering import (
    AttributionDimension,
    ExtensionMeter,
    ExtensionMeteringError,
    ExtensionQuotaBalance,
    ExtensionQuotaConflict,
    ExtensionQuotaDenied,
    ExtensionQuotaLedger,
    ExtensionQuotaPolicy,
    ExtensionQuotaRequest,
    ExtensionUsageAmounts,
    ExtensionUsageConflict,
    ExtensionUsageEvent,
    UsageTotals,
)
from maistro.extensions.resolution import (
    LOCK_FORMAT,
    ROOT_REQUEST_ORIGIN,
    SELECTION_POLICY,
    CatalogEntry,
    ConstraintRecord,
    DependencyCycle,
    ExtensionCatalog,
    ExtensionDependency,
    LockArtifacts,
    LockDiff,
    LockEntry,
    LockFormatError,
    LockKind,
    LockState,
    MissingLockArtifacts,
    RejectedCandidate,
    ResolutionConflict,
    ResolutionError,
    RootRequest,
    SelectionExplanation,
    SkippedOptional,
    UnresolvableDependency,
    diff_locks,
    materialize_lock,
    resolve_lock,
)
from maistro.extensions.semver import (
    InvalidSemanticVersion,
    InvalidVersionRange,
    SemVer,
    VersionRange,
    parse_range,
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
    "LOCK_FORMAT",
    "ROOT_REQUEST_ORIGIN",
    "SELECTION_POLICY",
    "SUPPORTED_MANIFEST_VERSION",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "TRUST_POLICY",
    "ActivationCallback",
    "ArtifactMismatch",
    "AttributionDimension",
    "AuthorityBaseline",
    "AuthorityDelta",
    "CatalogEntry",
    "CompatibilityPolicy",
    "CompatibilityReport",
    "ConstraintRecord",
    "DependencyCycle",
    "ExtensionCatalog",
    "ExtensionCodeLoader",
    "ExtensionDependency",
    "ExtensionEntryPoint",
    "ExtensionIdentityConflict",
    "ExtensionInstallRecord",
    "ExtensionInstallService",
    "ExtensionInstallStore",
    "ExtensionLifecycleError",
    "ExtensionManifest",
    "ExtensionMeter",
    "ExtensionMeteringError",
    "ExtensionPackage",
    "ExtensionQuotaBalance",
    "ExtensionQuotaConflict",
    "ExtensionQuotaDenied",
    "ExtensionQuotaLedger",
    "ExtensionQuotaPolicy",
    "ExtensionQuotaRequest",
    "ExtensionRegistryError",
    "ExtensionScope",
    "ExtensionState",
    "ExtensionStore",
    "ExtensionTransition",
    "ExtensionUsageAmounts",
    "ExtensionUsageConflict",
    "ExtensionUsageEvent",
    "InMemoryExtensionInstallStore",
    "InMemoryExtensionStore",
    "InspectionConflict",
    "InstallRecord",
    "InstallRequest",
    "InvalidSemanticVersion",
    "InvalidTransition",
    "InvalidVersionRange",
    "LoadedExtension",
    "LockArtifacts",
    "LockDiff",
    "LockEntry",
    "LockFormatError",
    "LockKind",
    "LockState",
    "ManifestRejected",
    "ManifestSnapshot",
    "MissingLockArtifacts",
    "PackageDigestMismatch",
    "PackageIdentity",
    "PackageSignatureInvalid",
    "PublisherIdentity",
    "PublisherKeyConflict",
    "RegistryProvenance",
    "RejectedCandidate",
    "ResolutionConflict",
    "ResolutionError",
    "RootRequest",
    "SelectionExplanation",
    "SemVer",
    "SkippedOptional",
    "SqliteExtensionInstallStore",
    "TrustClaim",
    "TrustEvidence",
    "TrustPolicy",
    "TrustReport",
    "UnknownInstall",
    "UnknownPublisher",
    "UnresolvableDependency",
    "UnwiredExtensionLoader",
    "UsageTotals",
    "VersionRange",
    "assert_snapshot_intact",
    "canonical_install_payload",
    "compute_authority_delta",
    "diff_locks",
    "evaluate_compatibility",
    "evaluate_trust",
    "identity_key",
    "inspect_manifest",
    "manifest_snapshot",
    "materialize_lock",
    "normalize_permission",
    "parse_range",
    "resolve_lock",
    "sha256_hex",
    "verify_package_payload",
]
