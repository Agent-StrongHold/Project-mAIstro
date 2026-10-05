"""Canonical extension lifecycle hooks (#950).

An extension implements :class:`ExtensionLifecycle` and nothing else. The
hooks receive only the public :class:`maistro.extensions.ExtensionContext` —
never a container, store, or host object — and every hook the host drives is
attributed to the extension identity on failure.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from maistro.extensions.context import ExtensionContext
from maistro.extensions.errors import ExtensionLifecycleError


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


async def run_activation(lifecycle: ExtensionLifecycle, context: ExtensionContext) -> None:
    """Drive ``activate`` with extension-attributed error handling."""
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
