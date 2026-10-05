"""The canonical sync engine: provenance stamping, checkpoints, tombstones.

This module is the host side of the connector SDK and the only path an item
may take from a connector into an ingest store. Three invariants carry the
issue's acceptance criteria:

* **Provenance is stamped here, once.** Every item a connector yields becomes
  a :class:`~maistro.connectors.types.SourceRecord` carrying connector id and
  version, source and external identity, item version, content hash, and the
  Workspace/config scope — before any store sees it.
* **Checkpoints commit after items.** The cursor is saved only after the
  page's items are in the ingest store. A crash in between replays the same
  cursor; version+hash dedup makes the replay idempotent, so restart loses
  nothing and duplicates nothing.
* **Deletion is explicit.** Only an item with ``deleted=True`` tombstones a
  record. A source falling silent changes nothing; a same-version item is
  skipped as UNCHANGED rather than re-ingested as a duplicate.

Upstream failures are normalized at the engine boundary: raw ``httpx``
exceptions escaping a connector become the canonical
:class:`~maistro.connectors.types.ConnectorUnavailableError` /
:class:`~maistro.connectors.types.ConnectorRateLimitedError`, with the
checkpoint untouched so a retry resumes from the same cursor.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx

from maistro.connectors.scope import ConnectorInstance, ConnectorSession, SyncContext
from maistro.connectors.types import (
    ConnectorCapability,
    ConnectorCapabilityError,
    ConnectorDescriptor,
    ConnectorError,
    ConnectorRateLimitedError,
    ConnectorUnavailableError,
    SourceItem,
    SourceRecord,
    SyncAction,
    SyncCursor,
    SyncOutcome,
    SyncPage,
    SyncReport,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.connectors.base import ConnectorSource

#: Config id used when a sync does not name one. Part of the checkpoint
#: address, so two configs of the same connector never share a cursor.
DEFAULT_CONFIG_ID = "default"

#: Upper bound on pages per run. A connector whose cursor never advances
#: fails loudly here instead of looping a sync forever.
_MAX_PAGES = 100


def content_hash(content: str) -> str:
    """Return the sha256 hex digest of ``content`` (the dedup fingerprint)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@runtime_checkable
class IngestStore(Protocol):
    """Durable home for provenance-stamped records, keyed by full identity."""

    async def get(
        self, workspace_id: str, connector_id: str, source_id: str, external_id: str
    ) -> SourceRecord | None:
        """Return the current record for one item identity, or None."""
        ...

    async def put(self, record: SourceRecord) -> None:
        """Persist ``record`` (insert or replace by identity)."""
        ...

    async def records(self, workspace_id: str, connector_id: str) -> tuple[SourceRecord, ...]:
        """Return every record one connector holds in one Workspace."""
        ...


class MemoryIngestStore:
    """In-process reference :class:`IngestStore`.

    Production hosts bind their own durable store to the protocol; this one
    exists so the engine and the conformance suite have a working
    implementation in-tree.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str, str], SourceRecord] = {}

    @staticmethod
    def _key(
        workspace_id: str, connector_id: str, source_id: str, external_id: str
    ) -> tuple[str, str, str, str]:
        return (workspace_id, connector_id, source_id, external_id)

    async def get(
        self, workspace_id: str, connector_id: str, source_id: str, external_id: str
    ) -> SourceRecord | None:
        return self._records.get(self._key(workspace_id, connector_id, source_id, external_id))

    async def put(self, record: SourceRecord) -> None:
        self._records[
            self._key(
                record.workspace_id, record.connector_id, record.source_id, record.external_id
            )
        ] = record

    async def records(self, workspace_id: str, connector_id: str) -> tuple[SourceRecord, ...]:
        return tuple(
            record
            for (ws, cid, _sid, _eid), record in sorted(self._records.items())
            if ws == workspace_id and cid == connector_id
        )


@runtime_checkable
class CheckpointStore(Protocol):
    """Durable home for sync cursors, addressed by the full scope triple."""

    async def load(self, workspace_id: str, connector_id: str, config_id: str) -> SyncCursor | None:
        """Return the saved cursor for one sync stream, or None."""
        ...

    async def save(self, cursor: SyncCursor) -> None:
        """Persist ``cursor`` (replace by scope triple)."""
        ...


class MemoryCheckpointStore:
    """In-process reference :class:`CheckpointStore`."""

    def __init__(self) -> None:
        self._cursors: dict[tuple[str, str, str], SyncCursor] = {}

    async def load(self, workspace_id: str, connector_id: str, config_id: str) -> SyncCursor | None:
        return self._cursors.get((workspace_id, connector_id, config_id))

    async def save(self, cursor: SyncCursor) -> None:
        self._cursors[(cursor.workspace_id, cursor.connector_id, cursor.config_id)] = cursor


class SyncEngine:
    """Drive one connector instance through a provenance-preserving sync."""

    def __init__(
        self,
        ingest: IngestStore,
        checkpoints: CheckpointStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ingest = ingest
        self._checkpoints = checkpoints
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now_iso(self) -> str:
        return self._clock().isoformat()

    async def run(
        self,
        source: ConnectorSource,
        instance: ConnectorInstance,
        *,
        workspace_id: str,
        config_id: str = DEFAULT_CONFIG_ID,
        config: Mapping[str, str] | None = None,
        query: str | None = None,
        max_pages: int = _MAX_PAGES,
    ) -> SyncReport:
        """Run one incremental sync; return the report and resume cursor.

        Raises :class:`ConnectorScopeError` for an undeclared Workspace,
        :class:`ConnectorCapabilityError` for an undeclared capability, and
        canonical connector errors for normalized upstream failures.
        """
        connector_id = instance.descriptor.connector_id
        self._require_capability(instance.descriptor, ConnectorCapability.LIST)
        if query is not None:
            self._require_capability(instance.descriptor, ConnectorCapability.QUERY)
        session = ConnectorSession.create(
            instance,
            workspace_id=workspace_id,
            config_id=config_id,
            config=config or {},
        )
        ctx = SyncContext(
            session=session,
            cursor=await self._resume(workspace_id, connector_id, config_id),
            query=query,
        )
        outcomes, cursor = await self._drain(
            source, ctx, max_pages, workspace_id, connector_id, config_id
        )
        return SyncReport(
            workspace_id=workspace_id,
            connector_id=connector_id,
            config_id=config_id,
            outcomes=tuple(outcomes),
            cursor=cursor,
        )

    async def fetch(
        self,
        source: ConnectorSource,
        instance: ConnectorInstance,
        *,
        workspace_id: str,
        external_id: str,
        config_id: str = DEFAULT_CONFIG_ID,
        config: Mapping[str, str] | None = None,
    ) -> SyncOutcome:
        """Refresh one item by identity (FETCH capability) and ingest it."""
        self._require_capability(instance.descriptor, ConnectorCapability.FETCH)
        session = ConnectorSession.create(
            instance,
            workspace_id=workspace_id,
            config_id=config_id,
            config=config or {},
        )
        ctx = SyncContext(session=session)
        item = await self._fetch_item(source, ctx, external_id)
        return await self._ingest_one(item, ctx)

    @staticmethod
    def _require_capability(
        descriptor: ConnectorDescriptor, capability: ConnectorCapability
    ) -> None:
        if capability not in descriptor.capabilities:
            msg = (
                f"connector {descriptor.connector_id!r} does not declare the "
                f"{capability.value!r} capability"
            )
            raise ConnectorCapabilityError(msg)

    async def _resume(self, workspace_id: str, connector_id: str, config_id: str) -> str | None:
        saved = await self._checkpoints.load(workspace_id, connector_id, config_id)
        return saved.cursor if saved is not None else None

    async def _drain(
        self,
        source: ConnectorSource,
        ctx: SyncContext,
        max_pages: int,
        workspace_id: str,
        connector_id: str,
        config_id: str,
    ) -> tuple[list[SyncOutcome], str | None]:
        """Consume pages until the cursor stream ends or the page budget does.

        Each page is committed before its cursor: the checkpoint advances only
        over items that are already in the ingest store, so a crash anywhere in
        the stream replays from the last committed cursor and dedup absorbs it.
        """
        outcomes: list[SyncOutcome] = []
        cursor = ctx.cursor
        for _ in range(max_pages):
            page = await self._next_page(source, ctx)
            for item in page.items:
                outcomes.append(await self._ingest_one(item, ctx))
            cursor = _advance(cursor, page)
            await self._save_cursor(workspace_id, connector_id, config_id, cursor)
            if page.next_cursor is None:
                return outcomes, cursor
            ctx = _with_cursor(ctx, page.next_cursor)
        msg = (
            f"connector {ctx.session.descriptor.connector_id!r} cursor did not "
            f"terminate within {max_pages} pages"
        )
        raise ConnectorError(msg)

    async def _save_cursor(
        self, workspace_id: str, connector_id: str, config_id: str, cursor: str | None
    ) -> None:
        await self._checkpoints.save(
            SyncCursor(
                workspace_id=workspace_id,
                connector_id=connector_id,
                config_id=config_id,
                cursor=cursor,
                updated_at=self._now_iso(),
            )
        )

    async def _next_page(self, source: ConnectorSource, ctx: SyncContext) -> SyncPage:
        """Call the capability-matched listing method, normalizing upstream failures."""
        try:
            return await _list_call(source, ctx)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _unavailable(exc, ctx) from exc
        except httpx.HTTPStatusError as exc:
            raise _status_error(exc, ctx) from exc

    async def _fetch_item(
        self, source: ConnectorSource, ctx: SyncContext, external_id: str
    ) -> SourceItem:
        try:
            return await source.fetch_item(ctx, external_id)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _unavailable(exc, ctx) from exc
        except httpx.HTTPStatusError as exc:
            raise _status_error(exc, ctx) from exc

    async def _ingest_one(self, item: SourceItem, ctx: SyncContext) -> SyncOutcome:
        """Decide, stamp provenance, persist — the only ingestion path."""
        session = ctx.session
        connector_id = session.descriptor.connector_id
        existing = await self._ingest.get(
            session.workspace_id, connector_id, item.source_id, item.external_id
        )
        action = _decide(existing, item)
        record = _record_for(item, session, self._now_iso())
        await self._ingest.put(record)
        return SyncOutcome(record=record, action=action)


async def _list_call(source: ConnectorSource, ctx: SyncContext) -> SyncPage:
    """Route to ``query_items`` on a query sync, else ``list_items``."""
    if ctx.query is not None:
        return await source.query_items(ctx)
    return await source.list_items(ctx)


def _advance(cursor: str | None, page: SyncPage) -> str | None:
    """The resume cursor after consuming ``page``.

    A page that names a next cursor advances to it. A page that ends the
    stream keeps the incoming cursor (or None on a first sync): the next run
    re-reads the same final page and dedup makes that free.
    """
    return page.next_cursor if page.next_cursor is not None else cursor


def _with_cursor(ctx: SyncContext, cursor: str) -> SyncContext:
    return SyncContext(session=ctx.session, cursor=cursor, query=ctx.query)


def _decide(existing: SourceRecord | None, item: SourceItem) -> SyncAction:
    """The four-action decision; deletion and duplicates are explicit."""
    if item.deleted:
        return _decide_deletion(existing)
    return _decide_live(existing, item)


def _decide_deletion(existing: SourceRecord | None) -> SyncAction:
    """A tombstone deletes once; replaying it changes nothing further."""
    if existing is not None and existing.deleted:
        return SyncAction.UNCHANGED
    return SyncAction.TOMBSTONED


def _decide_live(existing: SourceRecord | None, item: SourceItem) -> SyncAction:
    """Ingest new items, skip identical ones, update drifted ones in place."""
    if existing is None:
        return SyncAction.INGESTED
    if existing.item_version == item.version and existing.content_hash == content_hash(
        item.content
    ):
        return SyncAction.UNCHANGED
    return SyncAction.UPDATED


def _record_for(item: SourceItem, session: ConnectorSession, now: str) -> SourceRecord:
    """Stamp canonical provenance onto an item (the single stamping site)."""
    return SourceRecord(
        connector_id=session.descriptor.connector_id,
        connector_version=session.descriptor.version,
        source_id=item.source_id,
        external_id=item.external_id,
        item_version=item.version,
        content_hash=content_hash(item.content),
        content=item.content,
        workspace_id=session.workspace_id,
        config_id=session.config_id,
        ingested_at=now,
        updated_at=item.updated_at,
        deleted=item.deleted,
    )


def _upstream_detail(exc: Exception, ctx: SyncContext) -> str:
    return f"{ctx.session.descriptor.connector_id!r} upstream failure: {exc}"


def _unavailable(exc: Exception, ctx: SyncContext) -> ConnectorUnavailableError:
    return ConnectorUnavailableError(_upstream_detail(exc, ctx))


def _retry_after(response: httpx.Response) -> float | None:
    """Parse the ``Retry-After`` header; seconds form only, else None."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _status_error(exc: httpx.HTTPStatusError, ctx: SyncContext) -> ConnectorError:
    """Map an upstream HTTP status failure onto the canonical error types."""
    status = exc.response.status_code
    if status == 429:
        return ConnectorRateLimitedError(
            _upstream_detail(exc, ctx),
            retry_after=_retry_after(exc.response),
        )
    return ConnectorUnavailableError(_upstream_detail(exc, ctx))
