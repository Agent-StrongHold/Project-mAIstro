"""The ``ConnectorSource`` port third-party connectors implement.

One class, four members — the whole surface an out-of-tree connector writes:

* ``descriptor`` — the immutable identity/requirement declaration;
* ``list_items`` — incremental listing, resumed from ``ctx.cursor`` (LIST);
* ``query_items`` — one query's matching items, read from ``ctx.query`` (QUERY);
* ``fetch_item`` — one item by identity, for refresh (FETCH).

Contract details connectors sign up to:

* pages are deterministic functions of their cursor (restart-safety replays
  the last committed cursor after a crash);
* ``fetch_item`` raises :class:`~maistro.connectors.types.ConnectorUnavailableError`
  for an identity the source does not know — never a bare ``KeyError``;
* upstream HTTP failures may escape raw; the engine normalizes them into the
  canonical error types, so connectors do not have to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.connectors.scope import SyncContext
    from maistro.connectors.types import ConnectorDescriptor, SourceItem, SyncPage


@runtime_checkable
class ConnectorSource(Protocol):
    """The SDK port. Implement it; do not subclass a host class."""

    @property
    def descriptor(self) -> ConnectorDescriptor:
        """Identity, capabilities, and declared secret refs."""
        ...

    async def list_items(self, ctx: SyncContext) -> SyncPage:
        """Return one incremental page, resuming from ``ctx.cursor``."""
        ...

    async def query_items(self, ctx: SyncContext) -> SyncPage:
        """Return the items matching ``ctx.query`` (QUERY capability)."""
        ...

    async def fetch_item(self, ctx: SyncContext, external_id: str) -> SourceItem:
        """Return one item by identity (FETCH capability)."""
        ...
