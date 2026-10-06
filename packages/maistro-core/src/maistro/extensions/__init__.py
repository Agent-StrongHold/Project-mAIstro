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
- **M9-C1 policy (issue #955, ``maistro.extensions.compat``)**: decides
  whether an extension's declared contract, features, and deprecation posture
  are compatible with this host — from metadata alone, before any code
  import.
- **M9-C2 resolution (issue #956)**: strict semantic-version ranges
  (``semver``), a deterministic resolver producing a reproducible
  :class:`LockState` (``resolution``), and lock-driven reinstall through the
  install store (:func:`materialize_lock`).
- **M9-C3 preflight (issue #957)**: host-upgrade compatibility preflight —
  :func:`run_preflight` evaluates the installed lock state against a target
  host contract (:class:`TargetHostContract`) built from public manifest
  metadata only, naming compatible, deprecated, migration-required and
  blocking extensions before the upgrade is applied. The target release is
  data, never imported code; nothing is activated.

No layer executes extension code: verification, evaluation, authorization,
resolution and contract negotiation all operate on bytes and declarations
alone.
"""

from __future__ import annotations

from maistro.extensions.authority import (
    AuthorityBaseline,
    AuthorityDelta,
    compute_authority_delta,
    normalize_permission,
)
from maistro.extensions.compat import (
    CONTRACT_VERSION,
    FEATURE_DEPRECATED,
    FEATURE_REMOVED,
    FEATURE_STATUSES,
    FEATURE_SUPPORTED,
    HOST_FEATURES,
    SUPPORTED_CONTRACT_MAJORS,
    CompatError,
    CompatibilityReport,
    CompatMetadataError,
    ContractRange,
    ContractVersion,
    Degradation,
    DeprecationNotice,
    ExtensionCompatMetadata,
    FeatureStatus,
    FeatureSupport,
    HostContractMetadata,
    IncompatibleContract,
    Verdict,
    ensure_compatible,
    negotiate,
    parse_compat_metadata,
    parse_contract_range,
    parse_contract_version,
    parse_feature_status,
)
from maistro.extensions.compatibility import (
    CompatibilityPolicy,
    evaluate_compatibility,
)
from maistro.extensions.effective_authority import (
    CallerAuthority,
    EffectiveAuthority,
    ExtensionAuthorityEvidence,
    ExtensionAuthorityInputs,
    HostExtensionPolicy,
    PermissionDenial,
    PublisherTrust,
    TrustTier,
    WorkspaceExtensionPolicy,
    compute_effective_authority,
    extension_family,
    resolve_publisher_trust,
)
from maistro.extensions.manifest import (
    SUPPORTED_MANIFEST_VERSION,
    assert_snapshot_intact,
    inspect_manifest,
    sha256_hex,
    verify_package_payload,
)
from maistro.extensions.preflight import (
    ExtensionStatus,
    PreflightPolicy,
    PreflightReport,
    TargetHostContract,
    run_preflight,
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

# NOTE: both `compat` (M9-C1 negotiation, #955) and `compatibility` (M9-B2
# activation, #953) define a class named `CompatibilityReport`. The package
# binds the M9-C1 negotiation report; the activation-layer report stays on
# its module path (`maistro.extensions.compatibility.CompatibilityReport`),
# which is how its in-tree consumers already import it.
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
    "CONTRACT_VERSION",
    "DIGEST_ALGORITHM",
    "FEATURE_DEPRECATED",
    "FEATURE_REMOVED",
    "FEATURE_STATUSES",
    "FEATURE_SUPPORTED",
    "HOST_FEATURES",
    "LOCK_FORMAT",
    "ROOT_REQUEST_ORIGIN",
    "SELECTION_POLICY",
    "SUPPORTED_CONTRACT_MAJORS",
    "SUPPORTED_MANIFEST_VERSION",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "TRUST_POLICY",
    "ActivationCallback",
    "ArtifactMismatch",
    "AuthorityBaseline",
    "AuthorityDelta",
    "CallerAuthority",
    "CatalogEntry",
    "CompatError",
    "CompatMetadataError",
    "CompatibilityPolicy",
    "CompatibilityReport",
    "ConstraintRecord",
    "ContractRange",
    "ContractVersion",
    "Degradation",
    "DependencyCycle",
    "DeprecationNotice",
    "EffectiveAuthority",
    "ExtensionAuthorityEvidence",
    "ExtensionAuthorityInputs",
    "ExtensionCatalog",
    "ExtensionCodeLoader",
    "ExtensionCompatMetadata",
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
    "ExtensionStatus",
    "ExtensionStore",
    "ExtensionTransition",
    "FeatureStatus",
    "FeatureSupport",
    "HostContractMetadata",
    "HostExtensionPolicy",
    "InMemoryExtensionInstallStore",
    "InMemoryExtensionStore",
    "IncompatibleContract",
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
    "PermissionDenial",
    "PreflightPolicy",
    "PreflightReport",
    "PublisherIdentity",
    "PublisherKeyConflict",
    "PublisherTrust",
    "RegistryProvenance",
    "RejectedCandidate",
    "ResolutionConflict",
    "ResolutionError",
    "RootRequest",
    "SelectionExplanation",
    "SemVer",
    "SkippedOptional",
    "SqliteExtensionInstallStore",
    "TargetHostContract",
    "TrustClaim",
    "TrustEvidence",
    "TrustPolicy",
    "TrustReport",
    "TrustTier",
    "UnknownInstall",
    "UnknownPublisher",
    "UnresolvableDependency",
    "UnwiredExtensionLoader",
    "Verdict",
    "VersionRange",
    "WorkspaceExtensionPolicy",
    "assert_snapshot_intact",
    "canonical_install_payload",
    "compute_authority_delta",
    "compute_effective_authority",
    "diff_locks",
    "ensure_compatible",
    "evaluate_compatibility",
    "evaluate_trust",
    "extension_family",
    "identity_key",
    "inspect_manifest",
    "manifest_snapshot",
    "materialize_lock",
    "negotiate",
    "normalize_permission",
    "parse_compat_metadata",
    "parse_contract_range",
    "parse_contract_version",
    "parse_feature_status",
    "parse_range",
    "resolve_lock",
    "resolve_publisher_trust",
    "run_preflight",
    "sha256_hex",
    "verify_package_payload",
]
