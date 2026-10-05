"""Canonical extension lifecycle hooks (#950).

An extension implements :class:`ExtensionLifecycle` and nothing else. The
hooks receive only the public :class:`maistro.extensions.ExtensionContext` —
never a container, store, or host object — and every hook the host drives is
attributed to the extension identity on failure.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from maistro.extensions.context import ExtensionContext
from maistro.extensions.errors import ExtensionLifecycleError, ScopeMismatch


@runtime_checkable
class ExtensionLifecycle(Protocol):
    """Activation, invocation, and deactivation hooks of one extension.

    ``activate`` runs once per workspace scope, outside any Attempt: its
    context carries the workspace/agent identifiers and declared
    configuration, with empty execution identifiers. ``invoke`` runs once per
    invocation inside an Attempt and returns the invocation result.
    ``deactivate`` mirrors ``activate``.

    Implementations must be pure asyncio callables over the given context;
    raising from any hook aborts the corresponding host operation with the
    extension identity attached (:class:`ExtensionLifecycleError`).
    """

    async def activate(self, context: ExtensionContext) -> None: ...

    async def invoke(self, context: ExtensionContext) -> Any: ...

    async def deactivate(self, context: ExtensionContext) -> None: ...


def _lifecycle_label(context: ExtensionContext, hook: str) -> str:
    return (
        f"extension {context.identity.extension_id!r} (version {context.identity.version}) {hook}"
    )


def _require_scope(context: ExtensionContext, hook: str, *, in_attempt: bool) -> None:
    """Enforce the hook/scope pairing before any hook code runs.

    Activation and deactivation occur outside any Attempt, so their contexts
    must carry no execution correlation; invocation occurs inside one and
    must carry all of it. Enforcing this in the exported drivers keeps a
    mismatched hook/context pair from ever reaching the extension — and from
    an activation/deactivation hook dispatching on a governed effect route
    that only an Attempt-scoped context may spend.
    """

    if context.scope.in_attempt is not in_attempt:
        expected = "inside" if in_attempt else "outside"
        raise ScopeMismatch(
            f"cannot run {_lifecycle_label(context, hook)}: {hook} occurs "
            f"{expected} an Attempt, but the context scope is "
            f"{'in' if context.scope.in_attempt else 'not in'} one"
        )


async def run_activation(lifecycle: ExtensionLifecycle, context: ExtensionContext) -> None:
    """Drive ``activate`` with extension-attributed error handling."""
    _require_scope(context, "activate", in_attempt=False)
    try:
        await lifecycle.activate(context)
    except ExtensionLifecycleError:
        raise
    except Exception as exc:
        raise ExtensionLifecycleError(
            f"{_lifecycle_label(context, 'activate')} failed: {exc}"
        ) from exc


async def run_invocation(lifecycle: ExtensionLifecycle, context: ExtensionContext) -> Any:
    """Drive ``invoke`` with extension-attributed error handling."""
    _require_scope(context, "invoke", in_attempt=True)
    try:
        return await lifecycle.invoke(context)
    except ExtensionLifecycleError:
        raise
    except Exception as exc:
        raise ExtensionLifecycleError(
            f"{_lifecycle_label(context, 'invoke')} failed: {exc}"
        ) from exc


async def run_deactivation(lifecycle: ExtensionLifecycle, context: ExtensionContext) -> None:
    """Drive ``deactivate`` with extension-attributed error handling."""
    _require_scope(context, "deactivate", in_attempt=False)
    try:
        await lifecycle.deactivate(context)
    except ExtensionLifecycleError:
        raise
    except Exception as exc:
        raise ExtensionLifecycleError(
            f"{_lifecycle_label(context, 'deactivate')} failed: {exc}"
        ) from exc


__all__ = [
    "ExtensionLifecycle",
    "run_activation",
    "run_deactivation",
    "run_invocation",
]
