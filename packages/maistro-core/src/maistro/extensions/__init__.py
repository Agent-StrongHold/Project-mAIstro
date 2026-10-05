"""Governed extension install lifecycle (#953, M9-B2) and post-install
lifecycle (#954, M9-B3).

The public surface of the extension lifecycle: types, the pure evaluation
modules (manifest, compatibility, trust, authority, preflight), the store
seam, and the state-machine service. Nothing in this package ever imports
extension code; activation runs only through the host-supplied
:class:`ExtensionCodeLoader`, and only after explicit authorization. After
activation, pin/upgrade/rollback/disable/remove move versions and authority
under the same audited transition discipline.
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
from maistro.extensions.store import ExtensionStore, InMemoryExtensionStore
from maistro.extensions.trust import TrustPolicy, TrustReport, evaluate_trust
from maistro.extensions.types import (
    INSPECT_SKIP_STATES,
    REMOVABLE_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    ArtifactMismatch,
    ExtensionDependency,
    ExtensionEntryPoint,
    ExtensionInstallRecord,
    ExtensionLifecycleError,
    ExtensionManifest,
    ExtensionPackage,
    ExtensionScope,
    ExtensionState,
    ExtensionTransition,
    InspectionConflict,
    InvalidTransition,
    ManifestRejected,
    PinConflict,
    PinEvent,
    PinRecord,
    PreflightError,
    RemovalNote,
    TrustEvidence,
    UnknownInstall,
)

__all__ = [
    "INSPECT_SKIP_STATES",
    "REMOVABLE_STATES",
    "SUPPORTED_MANIFEST_VERSION",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "ArtifactMismatch",
    "AuthorityBaseline",
    "AuthorityDelta",
    "CompatibilityPolicy",
    "CompatibilityReport",
    "ExtensionCodeLoader",
    "ExtensionDependency",
    "ExtensionEntryPoint",
    "ExtensionInstallRecord",
    "ExtensionInstallService",
    "ExtensionLifecycleError",
    "ExtensionManifest",
    "ExtensionPackage",
    "ExtensionScope",
    "ExtensionState",
    "ExtensionStore",
    "ExtensionTransition",
    "InMemoryExtensionStore",
    "InspectionConflict",
    "InvalidTransition",
    "LoadedExtension",
    "ManifestRejected",
    "OwnedResourceJanitor",
    "PinConflict",
    "PinEvent",
    "PinRecord",
    "PreflightCheck",
    "PreflightError",
    "PreflightReport",
    "RemovalNote",
    "RetainAllJanitor",
    "TrustEvidence",
    "TrustPolicy",
    "TrustReport",
    "UnknownInstall",
    "UnwiredExtensionLoader",
    "assert_snapshot_intact",
    "compute_authority_delta",
    "evaluate_compatibility",
    "evaluate_trust",
    "inspect_manifest",
    "normalize_permission",
    "rollback_preflight",
    "sha256_hex",
    "upgrade_preflight",
    "verify_package_payload",
]
