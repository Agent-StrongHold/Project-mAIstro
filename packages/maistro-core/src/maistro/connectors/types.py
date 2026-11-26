"""Public contract types for the connector/source SDK (M9-E2, issue #963).

A third-party connector participates in canonical knowledge ingestion without
core edits. Everything in this module is the import surface such a connector
is allowed to depend on: descriptors that declare what the connector is and
what it needs, item/record shapes that carry canonical provenance, checkpoint
cursors that make incremental sync restart-safe, and the canonical error types
the host normalizes upstream failures into.

Provenance rule (the load-bearing one): a :class:`SourceItem` is what a
connector yields and carries no host context. The sync engine stamps it into a
:class:`SourceRecord`, and *every* ingestion path goes through that stamp, so
no item can reach an ingest store without connector/source/version/workspace
provenance attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ConnectorCapability(StrEnum):
    """What a connector can be asked to do; declared on its descriptor.

    The sync engine refuses to drive a capability the descriptor does not
    declare — a connector that never implemented ``query_items`` must fail at
    the gate, not with an AttributeError deep inside a sync run.
    """

    LIST = "list"
    QUERY = "query"
    FETCH = "fetch"


@dataclass(frozen=True)
class SecretRef:
    """A declared secret requirement, by name.

    ``name`` is the handle connector code passes to
    :meth:`maistro.connectors.scope.ConnectorSession.resolve_secret`;
    ``description`` states what the secret unlocks. The description is part of
    the contract, not decoration: conformance refuses a declared secret that
    does not document itself, because an operator cannot approve what they
    cannot read.
    """

    name: str
    description: str


@dataclass(frozen=True)
class ConnectorDescriptor:
    """Immutable identity and requirement declaration for one connector.

    ``connector_id`` is namespaced (``vendor.connector``) so third-party
    connectors cannot collide with built-ins or each other. ``version`` is an
    opaque token stamped onto every ingested record so provenance survives
    connector upgrades.
    """

    connector_id: str
    version: str
    capabilities: frozenset[ConnectorCapability] = field(default_factory=frozenset)
    secret_refs: tuple[SecretRef, ...] = ()


@dataclass(frozen=True)
class SourceItem:
    """One item as a connector yields it: identity, content, freshness.

    ``version`` is the connector's own freshness token (etag, updated_at,
    revision id — opaque to the host). Two items with the same identity and
    the same version are the same content: the engine skips them instead of
    re-ingesting duplicates. ``deleted=True`` is an explicit tombstone; the
    engine never infers deletions from a source falling silent.
    """

    source_id: str
    external_id: str
    content: str
    version: str
    updated_at: str | None = None
    deleted: bool = False


@dataclass(frozen=True)
class SourceRecord:
    """A :class:`SourceItem` stamped with canonical provenance at ingestion.

    This is the shape every ingest store persists. The connector identity
    (``connector_id`` + ``connector_version``), the source identity, the item
    version at ingest time, and the Workspace/config scope are all mandatory
    fields — an ingestion path that cannot fill them does not exist.
    """

    connector_id: str
    connector_version: str
    source_id: str
    external_id: str
    item_version: str
    content_hash: str
    content: str
    workspace_id: str
    config_id: str
    ingested_at: str
    updated_at: str | None = None
    deleted: bool = False


@dataclass(frozen=True)
class SyncCursor:
    """A durable incremental-sync checkpoint, scoped to one sync stream.

    The scope triple (``workspace_id``, ``connector_id``, ``config_id``) is
    the checkpoint's whole address: a checkpoint saved for one Workspace or
    config is never handed back for another, so two tenants syncing the same
    connector cannot advance each other's cursors.
    """

    workspace_id: str
    connector_id: str
    config_id: str
    cursor: str | None
    updated_at: str


@dataclass(frozen=True)
class SyncPage:
    """One page of a listing: items plus the incremental cursor to resume from.

    ``next_cursor is None`` means the stream is exhausted for now. A connector
    must return the same page for the same cursor — a sync that crashes between
    committing items and saving the checkpoint replays the cursor, and replay
    is only safe when pages are deterministic functions of their cursor.
    """

    items: tuple[SourceItem, ...]
    next_cursor: str | None = None


class SyncAction(StrEnum):
    """What the engine did with one item during a sync."""

    INGESTED = "ingested"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    TOMBSTONED = "tombstoned"


@dataclass(frozen=True)
class SyncOutcome:
    """One item's post-sync record paired with the action taken on it."""

    record: SourceRecord
    action: SyncAction


@dataclass(frozen=True)
class SyncReport:
    """Result of one sync run: every outcome plus the cursor to resume from."""

    workspace_id: str
    connector_id: str
    config_id: str
    outcomes: tuple[SyncOutcome, ...] = ()
    cursor: str | None = None

    def _count(self, action: SyncAction) -> int:
        return sum(1 for outcome in self.outcomes if outcome.action is action)

    @property
    def ingested(self) -> int:
        """Items newly ingested by this run."""
        return self._count(SyncAction.INGESTED)

    @property
    def updated(self) -> int:
        """Items whose version/content changed and were re-ingested in place."""
        return self._count(SyncAction.UPDATED)

    @property
    def unchanged(self) -> int:
        """Items skipped because identity, version, and content all matched."""
        return self._count(SyncAction.UNCHANGED)

    @property
    def tombstoned(self) -> int:
        """Items explicitly deleted at the source and recorded as tombstones."""
        return self._count(SyncAction.TOMBSTONED)


class ConnectorError(RuntimeError):
    """Base class for every canonical connector error.

    Connectors raise (or have normalized for them) the subclasses below; the
    host maps nothing else. An upstream failure that escapes as a raw HTTP or
    transport exception is an SDK contract violation, not a host concern.
    """


class ConnectorScopeError(ConnectorError):
    """A connector touched a Workspace or secret it did not declare.

    Raised by the host, never catchable into compliance: the only fix is
    widening the connector's declaration or the instance's binding, and the
    refusal is the security boundary working.
    """


class ConnectorCapabilityError(ConnectorError):
    """The host was asked to drive a capability the descriptor does not declare."""


class ConnectorUnavailableError(ConnectorError):
    """The upstream source could not be reached or answered unusably.

    The normalized shape of timeouts, connection failures, and unexpected
    upstream statuses. Sync runs surface this to callers; the checkpoint is
    left untouched so the next run resumes from the same cursor.
    """


class ConnectorRateLimitedError(ConnectorError):
    """The upstream source answered 429; retry after ``retry_after`` seconds.

    ``retry_after`` is the parsed ``Retry-After`` header when the upstream
    sent one, else ``None``. The engine leaves the checkpoint untouched so a
    retry resumes at the same cursor instead of skipping the throttled page.
    """

    retry_after: float | None

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after
