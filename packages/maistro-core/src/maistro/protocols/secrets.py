"""Secrets backend protocol — abstraction over K8s, Vault, and env-var providers.

A `SecretBackend` is the load-bearing seam between the config layer
and whichever store actually holds sensitive material at runtime. The protocol
itself is intentionally tiny: resolve a reference, watch for rotations, close.

Reference syntax:

    ${secret:k8s/<namespace>/<secret-name>/<key>}
    ${secret:vault/<mount>/<path>/<key>}
    ${secret:env/<VAR_NAME>}

The first segment after `secret:` is the backend tag and selects which
implementation handles the lookup. Backends are registered with the DI
container; callers never import a concrete backend directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True)
class SecretResult:
    """A resolved secret value plus the version stamp the backend reported."""

    value: str
    version: str | None = None


@runtime_checkable
class SecretBackend(Protocol):
    """Resolve and watch secret references from a backing store."""

    async def get_secret(self, ref: str) -> SecretResult:
        """Resolve a secret reference to its current value.

        Args:
            ref: A backend-specific reference. The leading ``${secret:...}``
                wrapper has already been stripped by the caller.

        Returns:
            A `SecretResult` with the current value and (when available) a
            backend version stamp.

        Raises:
            ValueError: The reference syntax is malformed.
            LookupError: The secret or key does not exist.
        """
        ...

    def watch_changes(self, ref: str) -> AsyncIterator[SecretResult]:
        """Yield a fresh `SecretResult` every time the backing secret changes."""
        ...

    async def close(self) -> None:
        """Release any background watchers, sockets, or pooled connections."""
        ...
