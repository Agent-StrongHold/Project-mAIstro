"""Governed extension registry persistence (M9-B1, issue #952) and the
extension install lifecycle (#953, M9-B2 / #954, M9-B3).

The public surface of the extension package, in two layers:

- the registry record layer: install records with publisher identity, package
  digest/signature metadata, manifest snapshots, catalog provenance and
  durable trust evidence, with in-memory and SQLite stores behind one
  protocol;
- the lifecycle layer: the pure evaluation modules (manifest, compatibility,
  trust, authority, preflight), the store seam, and the state-machine
  service. Nothing in this package ever imports extension code; activation
  runs only through the host-supplied :class:`ExtensionCodeLoader`, and only
  after explicit authorization. After activation, pin/upgrade/rollback/
  disable/remove move versions and authority under the same audited
  transition discipline.
"""

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
    verify_package_payload,
)
from maistro.extensions.preflight import (
    PreflightCheck,
    PreflightReport,
    rollback_preflight,
    upgrade_preflight,
)
from maistro.extensions.service import (
    ExtensionCodeLoader,
    ExtensionInstallService,
    LoadedExtension,
    OwnedResourceJanitor,
    RetainAllJanitor,
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
    INSPECT_SKIP_STATES,
    REMOVABLE_STATES,
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
    OperatorTrustEvidence,
    PackageDigestMismatch,
    PackageIdentity,
    PackageSignatureInvalid,
    PinConflict,
    PinEvent,
    PinRecord,
    PreflightError,
    PublisherIdentity,
    PublisherKeyConflict,
    RegistryProvenance,
    RemovalNote,
    TrustEvidence,
    UnknownInstall,
    UnknownPublisher,
    canonical_install_payload,
    identity_key,
    manifest_snapshot,
    sha256_hex,
)

__all__ = [
    "DIGEST_ALGORITHM",
    "INSPECT_SKIP_STATES",
    "REMOVABLE_STATES",
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
    "OperatorTrustEvidence",
    "OwnedResourceJanitor",
    "PackageDigestMismatch",
    "PackageIdentity",
    "PackageSignatureInvalid",
    "PinConflict",
    "PinEvent",
    "PinRecord",
    "PreflightCheck",
    "PreflightError",
    "PreflightReport",
    "PublisherIdentity",
    "PublisherKeyConflict",
    "RegistryProvenance",
    "RemovalNote",
    "RetainAllJanitor",
    "SqliteExtensionInstallStore",
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
    "rollback_preflight",
    "sha256_hex",
    "upgrade_preflight",
    "verify_package_payload",
]
