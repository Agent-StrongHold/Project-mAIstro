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

No layer executes extension code: verification, evaluation, authorization
and resolution all operate on bytes and declarations alone.

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
from maistro.extensions.compatibility import (
    CompatibilityPolicy,
    CompatibilityReport,
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
    "AuthorityBaseline",
    "AuthorityDelta",
    "CatalogEntry",
    "CompatibilityPolicy",
    "CompatibilityReport",
    "ConfigurationKeyNotDeclared",
    "ConstraintRecord",
    "DependencyCycle",
    "EffectDispatcher",
    "EffectNotDeclared",
    "EffectReceipt",
    "EffectRoute",
    "EventStoreProgressSink",
    "ExtensionCancellation",
    "ExtensionCancelled",
    "ExtensionCatalog",
    "ExtensionCodeLoader",
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
    "ExtensionLifecycle",
    "ExtensionLifecycleError",
    "ExtensionManifest",
    "ExtensionPackage",
    "ExtensionProgress",
    "ExtensionRegistryError",
    "ExtensionScope",
    "ExtensionState",
    "ExtensionStatus",
    "ExtensionStore",
    "ExtensionTransition",
    "GovernedEffectRoute",
    "InMemoryExtensionInstallStore",
    "InMemoryExtensionStore",
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
    "PreflightPolicy",
    "PreflightReport",
    "ProgressReporter",
    "ProgressSink",
    "PublisherIdentity",
    "PublisherKeyConflict",
    "RegistryProvenance",
    "RejectedCandidate",
    "ResolutionConflict",
    "ResolutionError",
    "RootRequest",
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
    "UngrantedProgressReporter",
    "UnknownInstall",
    "UnknownPublisher",
    "UnresolvableDependency",
    "UnwiredExtensionLoader",
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
    "run_activation",
    "run_deactivation",
    "run_invocation",
    "run_preflight",
    "sha256_hex",
    "verify_package_payload",
]
