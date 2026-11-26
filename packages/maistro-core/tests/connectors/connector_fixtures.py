"""Connector fixtures shared by the SDK test modules.

Two families live here:

* :class:`ScriptedConnector` — a deterministic in-memory source used to drive
  the engine through exact scenarios (paging, refresh, tombstones, faults).
* :class:`ExternalStyleConnector` — a connector written the way a third party
  would write one, importing **only** ``maistro.connectors`` public surface.

The `connectors.connector_fixtures` module path is also what the CLI tests
hand to ``maistro connectors verify`` to prove the operator command loads an
out-of-tree connector by dotted path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# Deliberately the whole import list a third-party connector needs: the public
# SDK surface and nothing from host internals.
from maistro.connectors import (
    ConnectorCapability,
    ConnectorDescriptor,
    ConnectorUnavailableError,
    SecretRef,
    SourceItem,
    SyncContext,
    SyncPage,
)


@dataclass(frozen=True)
class Page:
    """One scripted listing page: items plus the cursor to resume from."""

    items: tuple[SourceItem, ...]
    next_cursor: str | None = None


class ScriptedConnector:
    """A deterministic LIST/QUERY/FETCH source driven by scripted pages.

    ``pages`` maps the incoming cursor to the page returned, so tests control
    exactly what each sync step sees. ``live`` is the mutable current state
    tests rewrite between syncs to simulate source-side change and deletion;
    when a page's item id is present in ``live``, the live copy is served so
    an edit is visible on the next replay of the same cursor.
    """

    def __init__(
        self,
        pages: Mapping[str | None, Page] | None = None,
        *,
        connector_id: str = "tests.scripted",
        version: str = "1.0.0",
        capabilities: frozenset[ConnectorCapability] = frozenset(
            {ConnectorCapability.LIST, ConnectorCapability.QUERY, ConnectorCapability.FETCH}
        ),
        secret_refs: tuple[SecretRef, ...] = (),
    ) -> None:
        if pages is None:
            pages = {
                None: Page(
                    items=(
                        SourceItem(
                            source_id="repo",
                            external_id="doc-1",
                            content="default scripted document",
                            version="v1",
                        ),
                    ),
                    next_cursor=None,
                )
            }
        self._pages = dict(pages)
        self._descriptor = ConnectorDescriptor(
            connector_id=connector_id,
            version=version,
            capabilities=capabilities,
            secret_refs=secret_refs,
        )
        self.live: dict[tuple[str, str], SourceItem] = {
            (item.source_id, item.external_id): item
            for page in pages.values()
            for item in page.items
        }

    @property
    def descriptor(self) -> ConnectorDescriptor:
        return self._descriptor

    def _serve(self, page: Page) -> SyncPage:
        # Serve the live copy of each item, and drop items the source no
        # longer lists: silence is how a feed stops carrying a document.
        items = tuple(
            self.live[(item.source_id, item.external_id)]
            for item in page.items
            if (item.source_id, item.external_id) in self.live
        )
        return SyncPage(items=items, next_cursor=page.next_cursor)

    async def list_items(self, ctx: SyncContext) -> SyncPage:
        return self._serve(self._pages[ctx.cursor])

    async def query_items(self, ctx: SyncContext) -> SyncPage:
        matched = tuple(
            item for item in self.live.values() if (ctx.query or "") in item.external_id
        )
        return SyncPage(items=matched, next_cursor=None)

    async def fetch_item(self, ctx: SyncContext, external_id: str) -> SourceItem:
        for (_source_id, item_id), item in self.live.items():
            if item_id == external_id:
                return item
        raise ConnectorUnavailableError(f"no item {external_id!r} at this source")


class ExternalStyleConnector(ScriptedConnector):
    """A connector exactly as a third party ships it (public SDK imports only).

    Functionally identical to :class:`ScriptedConnector`; its role in the
    suite is to prove the shared conformance passes an implementation that
    never touched host internals, and that the CLI loads it by dotted path.
    Zero-arg constructible on purpose: the CLI loads classes, not closures.
    """


class DeclaringSecretsConnector(ScriptedConnector):
    """Zero-arg connector that declares one described secret (CLI describe)."""

    def __init__(self) -> None:
        super().__init__(
            connector_id="vendor.secrets",
            secret_refs=(SecretRef(name="api_token", description="Upstream API token"),),
        )


class SecretUsingConnector(ScriptedConnector):
    """Zero-arg connector that resolves its declared secret during listing.

    This is the connector shape that exposed the CLI gap: it needs its token
    to list, so a verify run without a provisioned value cannot exercise the
    sync at all. ``maistro connectors verify --secret api_token=...`` is the
    operator path that makes such a connector verifiable.
    """

    def __init__(self) -> None:
        super().__init__(
            connector_id="vendor.secretuser",
            secret_refs=(SecretRef(name="api_token", description="Upstream API token"),),
        )

    async def list_items(self, ctx: SyncContext) -> SyncPage:
        await ctx.session.resolve_secret("api_token")
        return await super().list_items(ctx)
