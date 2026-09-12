"""Live permission sources for Sentinel (#1165, ADR-072726-0d6b).

A :class:`PermissionSource` is the decision-time authority Sentinel consults
for tool authorization. Unlike the static ``permission_table`` a Sentinel is
constructed with, a source is resolved on every ``pre_call`` / ``authorize``,
so canonical Capability/Binding state changes -- a capability slot disabled at
runtime, a deployment permission edit -- are reflected in the very next
decision, without a process restart.

The fail-closed contract (#1165): a source that returns ``None`` or raises
provides *no permission decision*, and absence of a decision cannot grant tool
authority. Sentinel treats both as a denial.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro.capabilities.registry import CapabilityRegistry
    from maistro.security._types import PermissionTable

logger = logging.getLogger("maistro.sentinel")


@runtime_checkable
class PermissionSource(Protocol):
    """Decision-time permission authority.

    Return the effective ``PermissionTable`` for the current instant, or
    ``None`` when no decision can be made (unavailable store, failed
    projection). Implementations must be safe to call concurrently with the
    mutations they read: Sentinel resolves one on every authorization.
    """

    async def current_table(self) -> PermissionTable | None: ...


class StaticPermissionSource:
    """Wrap a fixed table; the non-live shape used by tests and trivial wiring.

    The table is held by reference, not copied: a caller who mutates it sees
    the mutation on the next resolution. Live sources are the production
    shape; this one exists so a static decision set can still cross the same
    seam.
    """

    def __init__(self, table: PermissionTable) -> None:
        self._table = table

    async def current_table(self) -> PermissionTable:
        return self._table


class CapabilityPermissionSource:
    """Project the canonical ``CapabilityRegistry``'s live state over a base table.

    This is the #1165 reconciliation with the canonical capability machinery:
    for a tool whose name *is* a defined capability slot, the registry's
    current enable state is part of the authority, read at decision time.
    Disabling a slot (``CapabilityRegistry.set_enabled(slot, False)``) revokes
    the matching tool's authorization at the next Sentinel decision -- no
    restart, no table redeploy. Re-enabling restores exactly the base table's
    decision, never more: this adapter only *removes* authority, it cannot
    grant a tool the deployment table does not name.

    Deliberate scoping:

    - A tool that is not a defined slot is governed by the base table alone.
      This adapter derives its gating from the registry itself rather than a
      hand-maintained tool-to-slot mapping -- a second hand-maintained tool
      authority is exactly what #1165 forbids.
    - Enable state is the authority gesture consulted here. Provider
      health/activation stays the registry's own resolution concern: Sentinel
      decides *authority*, not infrastructure availability.
    - Binding-scoped tool authorization (Workspace/Project/Node resolution at
      this boundary) needs execution identity Sentinel's lookup does not
      carry; that is #804's governed tool-use work, and it plugs in as another
      ``PermissionSource`` without touching Sentinel.
    """

    def __init__(self, base: PermissionTable, capabilities: CapabilityRegistry) -> None:
        self._base = base
        self._capabilities = capabilities

    async def current_table(self) -> PermissionTable:
        table = dict(self._base)
        for slot in self._capabilities.slots():
            if not self._capabilities.is_enabled(slot):
                table.pop(slot, None)
        return table


async def resolve_live_table(source: PermissionSource) -> PermissionTable | None:
    """Resolve a source to a table, or ``None`` when it cannot decide.

    Every failure mode -- raised exception, ``None`` return -- collapses to
    ``None`` so the caller's single fail-closed branch covers them all. A
    broken source must never widen authority by surfacing as an error a
    caller might be tempted to handle permissively.
    """
    try:
        return await source.current_table()
    except Exception:
        logger.warning("Permission source failed; denying fail-closed", exc_info=True)
        return None


__all__ = [
    "CapabilityPermissionSource",
    "PermissionSource",
    "StaticPermissionSource",
    "resolve_live_table",
]
