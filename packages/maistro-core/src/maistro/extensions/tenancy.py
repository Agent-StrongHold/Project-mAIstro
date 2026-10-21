"""Tenant-keyed extension configuration, caches, and checkpoints (#971).

Every piece of extension runtime state lives under the full tenant triple
``(org_id, workspace_id, extension_id)``. Nothing in this module accepts a
bare extension id, so no operation can alias one tenant's state onto
another's: a Workspace that asks for a key another Workspace set observes
absence, never the value. That is the structural half of the noninterference
acceptance — the policy engine gates *invocation*, this scoping gates
*observability and state*, and neither can be talked past the other tenant.

The in-memory implementation is the reference; a durable backend can arrive
behind the same keying without touching callers, because callers only ever
see :class:`ScopeBoundExtensionState` handles minted for exactly one scope.
"""

from __future__ import annotations

from maistro.extensions.types import ExtensionScope


def tenant_scope_key(scope: ExtensionScope, extension_id: str) -> tuple[str, str, str]:
    """The canonical tenant key: (org, workspace, extension).

    Workspace-scoped and org-only installs occupy different key spaces by
    construction — a blank ``workspace_id`` is its own (legitimate) tenant,
    never a wildcard.
    """
    if not extension_id.strip():
        raise ValueError("extension_id is required for tenant-scoped extension state")
    return (scope.org_id, scope.workspace_id, extension_id)


def _require_key_part(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required for tenant-scoped extension state")
    return value


class ScopeBoundExtensionState:
    """Configuration/cache/checkpoint handles for ONE extension in ONE scope.

    Returned by :meth:`TenantScopedExtensionState.bind`; every key used
    through this handle is implicitly namespaced by the bound tenant triple.
    """

    def __init__(self, runtime: TenantScopedExtensionState, key: tuple[str, str, str]) -> None:
        self._runtime = runtime
        self._key = key

    # -- configuration -----------------------------------------------------

    def set_config(self, key: str, value: str) -> None:
        """Set one configuration value for the bound tenant."""
        self._runtime._config.setdefault(self._key, {})[_require_key_part(key, "config key")] = (
            value
        )

    def get_config(self, key: str) -> str | None:
        """The tenant's configuration value, or ``None`` when unset.

        A foreign tenant's value for the same extension/key is indistinguishable
        from an unset one — observability is scoped, not error-signaled.
        """
        return self._runtime._config.get(self._key, {}).get(_require_key_part(key, "config key"))

    def delete_config(self, key: str) -> bool:
        """Delete one configuration value; True when this tenant held it."""
        bucket = self._runtime._config.get(self._key)
        if bucket is None:
            return False
        return bucket.pop(_require_key_part(key, "config key"), None) is not None

    # -- caches ------------------------------------------------------------

    def cache_set(self, key: str, value: bytes) -> None:
        """Write one cache entry under the tenant's namespace."""
        self._runtime._cache.setdefault(self._key, {})[_require_key_part(key, "cache key")] = value

    def cache_get(self, key: str) -> bytes | None:
        """The tenant's cache entry, or ``None`` — never another tenant's."""
        return self._runtime._cache.get(self._key, {}).get(_require_key_part(key, "cache key"))

    def cache_delete(self, key: str) -> bool:
        """Drop one cache entry; True when this tenant held it."""
        bucket = self._runtime._cache.get(self._key)
        if bucket is None:
            return False
        return bucket.pop(_require_key_part(key, "cache key"), None) is not None

    # -- checkpoints ---------------------------------------------------------

    def checkpoint_save(self, name: str, data: bytes) -> None:
        """Persist one checkpoint for the bound tenant."""
        self._runtime._checkpoints.setdefault(self._key, {})[
            _require_key_part(name, "checkpoint name")
        ] = data

    def checkpoint_load(self, name: str) -> bytes | None:
        """Load one of this tenant's checkpoints, or ``None``."""
        return self._runtime._checkpoints.get(self._key, {}).get(
            _require_key_part(name, "checkpoint name")
        )

    def checkpoint_names(self) -> tuple[str, ...]:
        """This tenant's checkpoint names — and only this tenant's."""
        return tuple(sorted(self._runtime._checkpoints.get(self._key, {})))


class TenantScopedExtensionState:
    """Owner of all tenant-keyed extension runtime state.

    One instance per process. Handles are minted only through :meth:`bind`,
    which is the single place a scope and an extension id become state keys.
    """

    def __init__(self) -> None:
        self._config: dict[tuple[str, str, str], dict[str, str]] = {}
        self._cache: dict[tuple[str, str, str], dict[str, bytes]] = {}
        self._checkpoints: dict[tuple[str, str, str], dict[str, bytes]] = {}

    def bind(self, scope: ExtensionScope, extension_id: str) -> ScopeBoundExtensionState:
        """Mint a state handle bound to one (scope, extension) tenant key."""
        return ScopeBoundExtensionState(self, tenant_scope_key(scope, extension_id))

    def clear_scope(self, scope: ExtensionScope, extension_id: str) -> int:
        """Drop every entry for one tenant key (removal lifecycle support).

        Returns the number of entries removed across config, cache and
        checkpoints. Other tenants are untouched.
        """
        key = tenant_scope_key(scope, extension_id)
        removed = 0
        for table in (self._config, self._cache, self._checkpoints):
            removed += len(table.pop(key, {}))
        return removed
