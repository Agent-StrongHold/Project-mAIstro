"""Error vocabulary for the canonical extension contract (#950).

Every least-authority refusal the extension context can produce is a distinct,
catchable type: an extension that asks for more authority than its descriptor
declares is told exactly which seam refused it, and a host integrator can
distinguish "the extension misbehaved" from "the platform denied authority".
"""

from __future__ import annotations


class ExtensionContractError(Exception):
    """Base class for every canonical extension-contract refusal."""


class ConfigurationKeyNotDeclared(ExtensionContractError, KeyError):
    """A configuration key was read that the extension never declared.

    Raised even when a value for the key exists host-side: an undeclared key
    reveals nothing, not even whether it is set (#950 declared-configuration
    access).
    """

    def __str__(self) -> str:  # KeyError.__str__ would repr() the sole arg
        return str(self.args[0]) if self.args else ""


class ServiceNotGranted(ExtensionContractError, LookupError):
    """A scoped service was requested that the host did not grant.

    The service must be declared by the extension descriptor *and* granted by
    the host; either half missing is the same refusal, so a descriptor can
    never widen authority by declaring something the operator did not grant.
    """


class EffectNotDeclared(ExtensionContractError, LookupError):
    """A capability effect was invoked that is not declared and routed.

    Authority-sensitive operations cross the canonical Capability → Provider →
    Binding → Invocation seam; an effect without both an extension declaration
    and a host-granted route has no canonical path and cannot execute.
    """


class ExtensionCancelled(ExtensionContractError):
    """The canonical execution owning this invocation was cancelled.

    Raised by :meth:`maistro.extensions.ExtensionCancellation.check` and
    :meth:`maistro.extensions.ExtensionCancellation.wait`. It reports the
    observation; the authoritative cancellation remains the canonical
    ``Run/NodeRun/Attempt`` fence that caused it.
    """


class ExtensionHookError(ExtensionContractError):
    """A lifecycle hook raised, attributed to the extension that raised it.

    Renamed from ``ExtensionLifecycleError`` at the develop sync: the
    governed-install flow (#952/#953) already exports ``ExtensionLifecycleError``
    as the base of its install-record failures, and one package cannot export
    two classes under one name. Hook failures keep the contract-error
    hierarchy; only the name changed.
    """


class ExtensionContractUnavailableError(ExtensionContractError):
    """A hook was used that the host did not wire for this invocation.

    Unlike the declaration refusals above this names a host wiring gap, not an
    extension overreach — but it still fails loudly rather than silently
    discarding what the extension asked for.
    """


class ScopeMismatch(ExtensionContractError, ValueError):
    """Canonical identifiers in an invocation scope are not correlated."""
