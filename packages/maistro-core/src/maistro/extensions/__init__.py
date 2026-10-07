"""Canonical public surface of the ``maistro.extensions`` package.

This package carries the extension surface of epic #938, in four layers:

- **M9-A2 runtime contract (#950, ADR-104)**: the interfaces through which an
  extension is activated, invoked, and deactivated, and the least-authority
  object it is handed while doing so. The contract, in one paragraph: an
  extension declares its maximum authority (config keys, services, effects)
  in an :class:`ExtensionDescriptor`; the host runtime composes that
  declaration with what it is willing to grant into one
  :class:`ExtensionContext` per invocation; and every authority-sensitive
  operation the extension can perform from that context crosses a canonical
  seam — governed ``Capability → Provider → Binding → Invocation`` dispatch
  for effects, the canonical ``Run/NodeRun/Attempt`` fence for cancellation,
  and correlated canonical events for progress and provenance. There is no
  ambient container access: a context holds no store, session, or container
  handle, and a refused seam raises instead of returning something empty.
  This layer deliberately does not define a scheduler, run store, execution
  authority, or extension loading/manifest machinery (manifest schema: #949).
  Physical execution truth remains owned by the canonical
  ``Graph → Run → NodeRun → Attempt`` chain; hosts drive extensions through
  :class:`ExtensionHost` from inside their existing Attempt execution.

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

Naming note: ``ExtensionLifecycleError`` is the governed-install failure base
(#952/#953). The #950 hook-failure wrapper — the error raised when an
extension's own ``activate``/``invoke``/``deactivate`` hook raises — is
:class:`ExtensionHookError`, a distinct ``ExtensionContractError`` subclass.
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
from maistro.extensions.context import (
    EffectDispatcher,
    EffectReceipt,
    ExtensionCancellation,
    ExtensionConfigView,
    ExtensionContext,
    ExtensionContractUnavailableError,
    ExtensionProgress,
    ProgressReporter,
    UngrantedProgressReporter,
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
from maistro.extensions.errors import (
    ConfigurationKeyNotDeclared,
    EffectNotDeclared,
    ExtensionCancelled,
    ExtensionContractError,
    ExtensionHookError,
    ScopeMismatch,
    ServiceNotGranted,
)
from maistro.extensions.host import (
    EffectRoute,
    EventStoreProgressSink,
    ExtensionHost,
    GovernedEffectRoute,
    ProgressSink,
)
from maistro.extensions.identity import (
    ExtensionDescriptor,
    ExtensionIdentity,
    InvocationScope,
)
from maistro.extensions.isolation import (
    DEFAULT_MIN_TIER,
    FILESYSTEM_READ_PERMISSION,
    FILESYSTEM_WRITE_PERMISSION,
    NETWORK_OUTBOUND_PERMISSION,
    REAL_ISOLATION_TIERS,
    ExtensionIsolationError,
    ExtensionIsolationProfile,
    ExtensionIsolationRefused,
    ExtensionRiskTier,
    ExtensionSandboxExecutionFailure,
    ExtensionSandboxOutcome,
    ExtensionSandboxPolicy,
    ExtensionSandboxRunner,
    ExtensionSandboxStartFailure,
    ExtensionSandboxViolation,
    InProcessExtensionLoader,
    SandboxViolationLog,
    ViolationKind,
    build_sandbox_config,
    risk_tier_for,
    select_isolation_profile,
)
from maistro.extensions.lifecycle import (
    ExtensionLifecycle,
    run_activation,
    run_deactivation,
    run_invocation,
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
    "DEFAULT_MIN_TIER",
    "DIGEST_ALGORITHM",
    "FEATURE_DEPRECATED",
    "FEATURE_REMOVED",
    "FEATURE_STATUSES",
    "FEATURE_SUPPORTED",
    "FILESYSTEM_READ_PERMISSION",
    "FILESYSTEM_WRITE_PERMISSION",
    "HOST_FEATURES",
    "LOCK_FORMAT",
    "NETWORK_OUTBOUND_PERMISSION",
    "REAL_ISOLATION_TIERS",
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
    "ConfigurationKeyNotDeclared",
    "ConstraintRecord",
    "ContractRange",
    "ContractVersion",
    "Degradation",
    "DependencyCycle",
    "DeprecationNotice",
    "EffectDispatcher",
    "EffectNotDeclared",
    "EffectReceipt",
    "EffectRoute",
    "EffectiveAuthority",
    "EventStoreProgressSink",
    "ExtensionAuthorityEvidence",
    "ExtensionAuthorityInputs",
    "ExtensionCancellation",
    "ExtensionCancelled",
    "ExtensionCatalog",
    "ExtensionCodeLoader",
    "ExtensionCompatMetadata",
    "ExtensionConfigView",
    "ExtensionContext",
    "ExtensionContractError",
    "ExtensionContractUnavailableError",
    "ExtensionDependency",
    "ExtensionDescriptor",
    "ExtensionEntryPoint",
    "ExtensionHookError",
    "ExtensionHost",
    "ExtensionIdentity",
    "ExtensionIdentityConflict",
    "ExtensionInstallRecord",
    "ExtensionInstallService",
    "ExtensionInstallStore",
    "ExtensionIsolationError",
    "ExtensionIsolationProfile",
    "ExtensionIsolationRefused",
    "ExtensionLifecycle",
    "ExtensionLifecycleError",
    "ExtensionManifest",
    "ExtensionPackage",
    "ExtensionProgress",
    "ExtensionRegistryError",
    "ExtensionRiskTier",
    "ExtensionSandboxExecutionFailure",
    "ExtensionSandboxOutcome",
    "ExtensionSandboxPolicy",
    "ExtensionSandboxRunner",
    "ExtensionSandboxStartFailure",
    "ExtensionSandboxViolation",
    "ExtensionScope",
    "ExtensionState",
    "ExtensionStatus",
    "ExtensionStore",
    "ExtensionTransition",
    "FeatureStatus",
    "FeatureSupport",
    "GovernedEffectRoute",
    "HostContractMetadata",
    "HostExtensionPolicy",
    "InMemoryExtensionInstallStore",
    "InMemoryExtensionStore",
    "InProcessExtensionLoader",
    "IncompatibleContract",
    "InspectionConflict",
    "InstallRecord",
    "InstallRequest",
    "InvalidSemanticVersion",
    "InvalidTransition",
    "InvalidVersionRange",
    "InvocationScope",
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
    "ProgressReporter",
    "ProgressSink",
    "PublisherIdentity",
    "PublisherKeyConflict",
    "PublisherTrust",
    "RegistryProvenance",
    "RejectedCandidate",
    "ResolutionConflict",
    "ResolutionError",
    "RootRequest",
    "SandboxViolationLog",
    "ScopeMismatch",
    "SelectionExplanation",
    "SemVer",
    "ServiceNotGranted",
    "SkippedOptional",
    "SqliteExtensionInstallStore",
    "TargetHostContract",
    "TrustClaim",
    "TrustEvidence",
    "TrustPolicy",
    "TrustReport",
    "TrustTier",
    "UngrantedProgressReporter",
    "UnknownInstall",
    "UnknownPublisher",
    "UnresolvableDependency",
    "UnwiredExtensionLoader",
    "Verdict",
    "VersionRange",
    "ViolationKind",
    "WorkspaceExtensionPolicy",
    "assert_snapshot_intact",
    "build_sandbox_config",
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
    "risk_tier_for",
    "run_activation",
    "run_deactivation",
    "run_invocation",
    "run_preflight",
    "select_isolation_profile",
    "sha256_hex",
    "verify_package_payload",
]
