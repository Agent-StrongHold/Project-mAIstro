"""Canonical public extension contract (#950) and registry persistence (#939).

This package carries two halves of the extension surface (epic #938):

- The runtime-facing SDK (M9-A2, #950, ADR-104): the interfaces through which
  an extension is activated, invoked, and deactivated, and the
  least-authority object it is handed while doing so. The contract, in one
  paragraph: an extension declares its maximum authority (config keys,
  services, effects) in an :class:`ExtensionDescriptor`; the host runtime
  composes that declaration with what it is willing to grant into one
  :class:`ExtensionContext` per invocation; and every authority-sensitive
  operation the extension can perform from that context crosses a canonical
  seam — governed ``Capability → Provider → Binding → Invocation`` dispatch
  for effects, the canonical ``Run/NodeRun/Attempt`` fence for cancellation,
  and correlated canonical events for progress and provenance. There is no
  ambient container access: a context holds no store, session, or container
  handle, and a refused seam raises instead of returning something empty.
  This half deliberately does not define a scheduler, run store, execution
  authority, or extension loading/manifest machinery (manifest schema: #949).
  Physical execution truth remains owned by the canonical
  ``Graph → Run → NodeRun → Attempt`` chain; hosts drive extensions through
  :class:`ExtensionHost` from inside their existing Attempt execution.

- Governed extension registry persistence (M9-B1, #939/#952): install
  records with publisher identity, package digest/signature metadata,
  manifest snapshots, catalog provenance and durable trust evidence. The
  inspect→authorize→install flow (#953) and the pin/upgrade/rollback
  lifecycle (#954) build on these records; nothing here executes extension
  code.
"""

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
    ExtensionLifecycleError,
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
    "ConfigurationKeyNotDeclared",
    "EffectDispatcher",
    "EffectNotDeclared",
    "EffectReceipt",
    "EffectRoute",
    "EventStoreProgressSink",
    "ExtensionCancellation",
    "ExtensionCancelled",
    "ExtensionConfigView",
    "ExtensionContext",
    "ExtensionContractError",
    "ExtensionContractUnavailableError",
    "ExtensionDescriptor",
    "ExtensionHost",
    "ExtensionIdentity",
    "ExtensionIdentityConflict",
    "ExtensionInstallStore",
    "ExtensionLifecycle",
    "ExtensionLifecycleError",
    "ExtensionProgress",
    "ExtensionRegistryError",
    "GovernedEffectRoute",
    "InMemoryExtensionInstallStore",
    "InstallRecord",
    "InstallRequest",
    "InvocationScope",
    "ManifestSnapshot",
    "PackageDigestMismatch",
    "PackageIdentity",
    "PackageSignatureInvalid",
    "ProgressReporter",
    "ProgressSink",
    "PublisherIdentity",
    "PublisherKeyConflict",
    "RegistryProvenance",
    "ScopeMismatch",
    "ServiceNotGranted",
    "SqliteExtensionInstallStore",
    "TrustEvidence",
    "UnknownPublisher",
    "UngrantedProgressReporter",
    "canonical_install_payload",
    "identity_key",
    "manifest_snapshot",
    "run_activation",
    "run_deactivation",
    "run_invocation",
    "sha256_hex",
]
