"""Governed extension registry and activation flow (M9-B, issues #952/#953).

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

No layer executes extension code: verification, evaluation and authorization
all operate on bytes and declarations alone.
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
    "CONTRACT_VERSION",
    "DIGEST_ALGORITHM",
    "FEATURE_DEPRECATED",
    "FEATURE_REMOVED",
    "FEATURE_STATUSES",
    "FEATURE_SUPPORTED",
    "HOST_FEATURES",
    "SUPPORTED_CONTRACT_MAJORS",
    "SUPPORTED_MANIFEST_VERSION",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "TRUST_POLICY",
    "ActivationCallback",
    "ArtifactMismatch",
    "AuthorityBaseline",
    "AuthorityDelta",
    "CompatError",
    "CompatMetadataError",
    "CompatibilityPolicy",
    "CompatibilityReport",
    "ContractRange",
    "ContractVersion",
    "Degradation",
    "DeprecationNotice",
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
    "ExtensionStore",
    "ExtensionTransition",
    "FeatureStatus",
    "FeatureSupport",
    "HostContractMetadata",
    "InMemoryExtensionInstallStore",
    "InMemoryExtensionStore",
    "IncompatibleContract",
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
    "Verdict",
    "assert_snapshot_intact",
    "canonical_install_payload",
    "compute_authority_delta",
    "ensure_compatible",
    "evaluate_compatibility",
    "evaluate_trust",
    "identity_key",
    "inspect_manifest",
    "manifest_snapshot",
    "negotiate",
    "normalize_permission",
    "parse_compat_metadata",
    "parse_contract_range",
    "parse_contract_version",
    "parse_feature_status",
    "sha256_hex",
    "verify_package_payload",
]
