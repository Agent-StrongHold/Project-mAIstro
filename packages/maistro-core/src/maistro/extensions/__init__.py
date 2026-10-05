"""Canonical public extension context and lifecycle contract (#950).

This module is the runtime-facing half of the extension SDK (epic #938): the
interfaces through which an extension is activated, invoked, and deactivated,
and the least-authority object it is handed while doing so.

The contract, in one paragraph: an extension declares its maximum authority
(config keys, services, effects) in an :class:`ExtensionDescriptor`; the host
runtime composes that declaration with what it is willing to grant into one
:class:`ExtensionContext` per invocation; and every authority-sensitive
operation the extension can perform from that context crosses a canonical
seam — governed ``Capability → Provider → Binding → Invocation`` dispatch for
effects, the canonical ``Run/NodeRun/Attempt`` fence for cancellation, and
correlated canonical events for progress and provenance. There is no ambient
container access: a context holds no store, session, or container handle, and
a refused seam raises instead of returning something empty.

This module deliberately does not define a scheduler, run store, execution
authority, or extension loading/manifest machinery (manifest schema: #949).
Physical execution truth remains owned by the canonical
``Graph → Run → NodeRun → Attempt`` chain; hosts drive extensions through
:class:`ExtensionHost` from inside their existing Attempt execution.
"""

from __future__ import annotations

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

__all__ = [
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
    "ExtensionLifecycle",
    "ExtensionLifecycleError",
    "ExtensionProgress",
    "GovernedEffectRoute",
    "InvocationScope",
    "ProgressReporter",
    "ProgressSink",
    "ScopeMismatch",
    "ServiceNotGranted",
    "UngrantedProgressReporter",
    "run_activation",
    "run_deactivation",
    "run_invocation",
]
