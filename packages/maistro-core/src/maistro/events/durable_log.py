"""Durable, append-only event log (ADR-086 / SPEC-070226-b234).

Events are appended before handling; a crash mid-handling replays from the
log on restart rather than dropping the event. The event API is append-only:
no event is ever mutated, and the one destructive path is retention's own
bounded ``purge_expired`` (#325), which deletes a legal-hold-aware oldest
batch and publishes the table's stored-volume health after committing.

Protocol-driven per maistro-core conventions: business logic depends on
``EventLogStore``; concrete implementations are in-memory (tests, homelab)
and SQLite (single-instance durability, aiosqlite — mirrors
``maistro.persistence.sqlite_*`` stores).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from maistro.events.bus import CANONICAL_EVENT_METADATA
from maistro.observability.metrics import (
    publish_retention_table_health,
    retention_health_probe_due,
    sqlite_table_sample,
)
from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade

if TYPE_CHECKING:
    from collections.abc import Sequence

    import aiosqlite

    from maistro.events.bus import Event


@dataclass(frozen=True)
class LoggedEvent:
    """An immutable event row in the durable log.

    ``id`` is a monotonically increasing integer assigned by the store on
    append; it doubles as the replay cursor for the processing loop.
    """

    id: int
    event_type: str
    entity_type: str = ""
    entity_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "payload": self.payload,
            "source": self.source,
            "created_at": self.created_at,
        }


@runtime_checkable
class EventLogStore(Protocol):
    """Append-only durable event log and its replay acknowledgements."""

    async def append(
        self,
        event_type: str,
        *,
        entity_type: str = "",
        entity_id: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "",
        source_event_id: str | None = None,
    ) -> LoggedEvent:
        """Persist a new event and return it with its assigned id.

        ``source_event_id`` carries the canonical Event identity a row was
        projected from (#2506). An append naming a source id already in the log
        returns that existing row instead of writing a second one: the
        legacy-bus bridge and the replay projector are two ingress paths for
        one canonical fact, and the durable trigger cursor treats every row as
        an occurrence, so the log itself must enforce one row per source event.
        """
        ...

    async def get(self, event_id: int) -> LoggedEvent | None:
        """Fetch a single event by id."""
        ...

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[LoggedEvent]:
        """Query events ascending by id.

        ``after_id``/``limit`` provide keyset pagination (pass the last id of
        the previous page as ``after_id``); ``event_type``, ``since`` and
        ``until`` filter by type and created_at time window.
        """
        ...

    async def get_replay_cursor(self, consumer_id: str) -> int:
        """Return the last event acknowledged by a durable consumer."""
        ...

    async def acknowledge_replay(self, consumer_id: str, event_id: int) -> int:
        """Durably acknowledge an event, never moving a cursor backwards."""
        ...

    async def prove_holes_absent(self, hole_ids: Sequence[int]) -> frozenset[int]:
        """Prove which hole ids can never become visible again, durably.

        A hole id is *terminally absent* when database evidence — not elapsed
        time — shows the append that allocated it has definitively ended
        without committing: no live transaction can still make the id
        visible, the id is not readable now, and the id allocator never
        reuses an id. A durable consumer may advance its cursor past such an
        id and no other; an id whose append could still commit (or whose
        absence the store cannot prove) must stay unproven, and the caller
        must keep its cursor below it (#2509). A visible id is never absent.
        """
        ...


def require_json_encodable_payload(payload: dict[str, Any]) -> None:
    """Reject a payload strict JSON cannot encode (NaN/Infinity, sets, ...).

    The canonical Event envelope already enforces this bound — its field-bounds
    check serializes with ``allow_nan=False`` — and ``request_digest_v1``
    re-serializes the logged body under the same rule at dispatch time. Append
    must therefore be the gate: a payload that was persisted but fails the
    digest would wedge the processing cursor forever, because the digest is
    computed before the receipt claim, so no receipt for that event could ever
    be claimed or settled.
    """
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        msg = f"event payload is not strictly JSON-encodable: {exc}"
        raise ValueError(msg) from exc


def append_from_bus_event(event: Event) -> dict[str, Any]:
    """Map an in-memory bus :class:`~maistro.events.bus.Event` to append() kwargs.

    A canonical projection carries its canonical identity in
    ``payload[CANONICAL_EVENT_METADATA]``; it becomes the row's
    ``source_event_id`` so the log can enforce one row per canonical Event
    across the bridge and the replay projector (#2506). Non-canonical bus
    events have no metadata and stay plain, unkeyed rows.
    """
    kwargs: dict[str, Any] = {
        "event_type": event.event_type,
        "entity_type": event.category.value,
        "entity_id": event.correlation_id,
        "payload": dict(event.payload),
        "source": event.source,
    }
    metadata = event.payload.get(CANONICAL_EVENT_METADATA)
    if isinstance(metadata, dict) and metadata.get("event_id"):
        kwargs["source_event_id"] = str(metadata["event_id"])
    return kwargs


class InMemoryEventLog:
    """In-memory :class:`EventLogStore` (tests, dry-run)."""

    def __init__(self) -> None:
        self._events: list[LoggedEvent] = []
        self._next_id = 1
        self._replay_cursors: dict[str, int] = {}
        self._by_source_event_id: dict[str, LoggedEvent] = {}
        self._lock = asyncio.Lock()

    async def append(
        self,
        event_type: str,
        *,
        entity_type: str = "",
        entity_id: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "",
        source_event_id: str | None = None,
    ) -> LoggedEvent:
        require_json_encodable_payload(payload or {})
        async with self._lock:
            if source_event_id is not None:
                existing = self._by_source_event_id.get(source_event_id)
                if existing is not None:
                    return existing
            event = LoggedEvent(
                id=self._next_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=dict(payload or {}),
                source=source,
            )
            self._next_id += 1
            self._events.append(event)
            if source_event_id is not None:
                self._by_source_event_id[source_event_id] = event
            return event

    async def get(self, event_id: int) -> LoggedEvent | None:
        for e in self._events:
            if e.id == event_id:
                return e
        return None

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[LoggedEvent]:
        result: list[LoggedEvent] = []
        for e in self._events:
            if e.id <= after_id:
                continue
            if event_type is not None and e.event_type != event_type:
                continue
            if since is not None and e.created_at < since:
                continue
            if until is not None and e.created_at > until:
                continue
            result.append(e)
            if len(result) >= limit:
                break
        return result

    async def get_replay_cursor(self, consumer_id: str) -> int:
        return self._replay_cursors.get(consumer_id, 0)

    async def acknowledge_replay(self, consumer_id: str, event_id: int) -> int:
        if event_id < 0:
            raise ValueError("event_id must be non-negative")
        async with self._lock:
            current = self._replay_cursors.get(consumer_id, 0)
            acknowledged = max(current, event_id)
            self._replay_cursors[consumer_id] = acknowledged
            return acknowledged

    async def prove_holes_absent(self, hole_ids: Sequence[int]) -> frozenset[int]:
        """Refuse every hole: an in-memory append has no outcome to prove.

        This store's appends are synchronous — there is no transaction whose
        outcome could leave an id allocated-but-uncommitted — so a hole here
        can only be synthetic (a test shim hiding ids from ``query``). No
        durable evidence exists to prove one absent, and inventing it would
        let a cursor cross an id a writer could still be filling. The safe
        answer is to prove nothing: the caller keeps its cursor below the
        first unproven hole until the id appears (#2509).
        """
        return frozenset()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_log_type_time
    ON event_log (event_type, created_at);
CREATE TABLE IF NOT EXISTS event_replay_cursors (
    consumer_id TEXT PRIMARY KEY,
    event_id INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
"""

#: Column added after the first release (#2506): the canonical-source identity
#: a row was projected from. NULL for legacy/non-canonical rows — SQLite unique
#: indexes treat NULLs as distinct, so unkeyed rows never collide, and the one
#: keyed row per canonical Event is what makes the bridge and the replay
#: projector two ingress paths onto one durable fact.
_SOURCE_COLUMN_UPGRADE = (
    "ALTER TABLE event_log ADD COLUMN source_event_id TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_event_log_source_event_id "
    "ON event_log (source_event_id)",
)


class SqliteEventLog:
    """SQLite-backed :class:`EventLogStore` (homelab / single-instance)."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SCHEMA)
            columns = await self._conn.execute("PRAGMA table_info(event_log)")
            present = {str(row[1]) for row in await columns.fetchall()}
            if "source_event_id" not in present:
                for upgrade in _SOURCE_COLUMN_UPGRADE:
                    await self._conn.execute(upgrade)
            await self._conn.commit()

    async def purge_expired(
        self,
        *,
        before: float,
        limit: int = 1_000,
        legal_hold_entity_ids: tuple[str, ...] = (),
    ) -> int:
        """Delete a bounded delivery-history batch after terminal processing."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        hold_sql = ""
        params: list[object] = [before]
        if legal_hold_entity_ids:
            marks = ",".join("?" for _ in legal_hold_entity_ids)
            hold_sql = f" AND entity_id NOT IN ({marks})"  # values remain bound
            params.extend(legal_hold_entity_ids)
        params.append(limit)
        # Serialized with append on the store lock: both write through the one
        # connection, and the purge's BEGIN IMMEDIATE must wait for an in-flight
        # append's transaction rather than start a second one on top of it.
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self._conn.execute(
                    "DELETE FROM event_log WHERE id IN (SELECT id FROM event_log "  # nosec B608 - hold_sql is ?-placeholders only, all values bound
                    "WHERE created_at < ?" + hold_sql + " ORDER BY id LIMIT ?)",
                    params,
                )
                await self._conn.commit()
                await self._publish_table_health()
                return max(cursor.rowcount, 0)
            except BaseException:
                await self._conn.rollback()
                raise

    async def _publish_table_health(self) -> None:
        """Publish the durable delivery log's stored volume after a purge (#325).

        The sweep contract's stored-volume clause: the purge counters are
        rates and cannot show a delivery log nobody is bounding, so the
        committed purge probes the table it governs and publishes the level.
        Throttled per store by the publisher; a quiet purge publishes too.
        """
        if not retention_health_probe_due("event_log:sqlite"):
            return
        sample = await sqlite_table_sample(
            self._conn, "event_log", "created_at", oldest_unit="unix_s"
        )
        if sample is not None:
            publish_retention_table_health(
                "event_log:sqlite", "sqlite", [sample], min_interval_s=0.0
            )

    async def append(
        self,
        event_type: str,
        *,
        entity_type: str = "",
        entity_id: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "",
        source_event_id: str | None = None,
    ) -> LoggedEvent:
        created_at = time.time()
        require_json_encodable_payload(payload or {})
        async with self._lock:
            if source_event_id is not None:
                # One row per canonical Event (#2506). The pre-check is exact
                # under this store's write lock; the INSERT's ON CONFLICT is
                # the guard for a writer this process cannot see.
                existing = await self._find_by_source(source_event_id)
                if existing is not None:
                    return existing
            cursor = await self._conn.execute(
                """INSERT INTO event_log
                   (event_type, entity_type, entity_id, payload, source, created_at,
                    source_event_id)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(source_event_id) DO NOTHING""",
                (
                    event_type,
                    entity_type,
                    entity_id,
                    json.dumps(payload or {}),
                    source,
                    created_at,
                    source_event_id,
                ),
            )
            await self._conn.commit()
            row_id = cursor.lastrowid
            if row_id is None and source_event_id is not None:
                existing = await self._find_by_source(source_event_id)
                if existing is not None:
                    return existing
            assert row_id is not None  # nosec B101 - INSERT always assigns a rowid
        return LoggedEvent(
            id=row_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=dict(payload or {}),
            source=source,
            created_at=created_at,
        )

    async def _find_by_source(self, source_event_id: str) -> LoggedEvent | None:
        cursor = await self._conn.execute(
            "SELECT id, event_type, entity_type, entity_id, payload, source, created_at "
            "FROM event_log WHERE source_event_id = ?",
            (source_event_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_event(tuple(row)) if row is not None else None

    async def get(self, event_id: int) -> LoggedEvent | None:
        cursor = await self._conn.execute(
            "SELECT id, event_type, entity_type, entity_id, payload, source, created_at "
            "FROM event_log WHERE id = ?",
            (event_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_event(tuple(row)) if row is not None else None

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[LoggedEvent]:
        conditions = ["id > ?"]
        params: list[Any] = [after_id]
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if since is not None:
            conditions.append("created_at >= ?")
            params.append(since)
        if until is not None:
            conditions.append("created_at <= ?")
            params.append(until)
        params.append(limit)
        query = (
            "SELECT id, event_type, entity_type, entity_id, payload, source, created_at "
            "FROM event_log WHERE " + " AND ".join(conditions) + " ORDER BY id ASC LIMIT ?"
        )
        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_event(tuple(r)) for r in rows]

    async def get_replay_cursor(self, consumer_id: str) -> int:
        cursor = await self._conn.execute(
            "SELECT event_id FROM event_replay_cursors WHERE consumer_id = ?",
            (consumer_id,),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def acknowledge_replay(self, consumer_id: str, event_id: int) -> int:
        if event_id < 0:
            raise ValueError("event_id must be non-negative")
        now = time.time()
        await self._conn.execute(
            """INSERT INTO event_replay_cursors (consumer_id, event_id, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(consumer_id) DO UPDATE SET
                 event_id = MAX(event_replay_cursors.event_id, excluded.event_id),
                 updated_at = excluded.updated_at""",
            (consumer_id, event_id, now),
        )
        await self._conn.commit()
        return await self.get_replay_cursor(consumer_id)

    async def prove_holes_absent(self, hole_ids: Sequence[int]) -> frozenset[int]:
        """Prove a hole terminally absent by becoming the one SQLite writer.

        SQLite serialises writers: at most one write transaction exists at a
        time per database. The proof therefore runs on an isolated connection
        to the same file — never on the shared spine connection. Every
        durable store `_wire_sqlite_durable_events` wires shares that
        connection, so a sibling's INSERT executed mid-proof would join this
        transaction and this rollback would silently discard it while the
        sibling still reported success — the exact #327/#1199/#101 failure
        this codebase already paid for three times.

        Taking the write lock (`BEGIN IMMEDIATE`, under a zero busy timeout
        so a held lock fails fast instead of stalling the tick) proves no
        other writer transaction is live — so every id any transaction
        allocated has terminated, and a re-read inside that same lock
        answers terminally: still invisible means the append rolled back,
        because the single-writer order makes id allocation and commit
        agree. A `database is locked` failure means a writer IS live and
        some hole may yet commit, so nothing is proven and the caller holds
        its cursor below the hole until a later tick (#2509).
        """
        if not hole_ids:
            return frozenset()
        path = await self._database_path()
        if path is None:
            # A pathless `sqlite://` is an in-memory database: an isolated
            # proof connection would open a different, empty database, and
            # a proof on the shared connection could roll back a sibling
            # store's uncommitted write. With isolation impossible, the
            # honest answer is the in-memory store's: prove nothing.
            return frozenset()
        # `self._lock` is intentionally not held: it guards only this
        # instance, while the isolated connection serialises against every
        # writer database-wide — which is the guarantee the proof needs.
        # Imported here, not at module scope: `aiosqlite` is core's optional
        # `sqlite` extra, and this module sits in every server/RSI import
        # graph (`maistro.events` re-exports `SqliteEventLog`), so a
        # top-level import made `import maistro_server.main` — and with it
        # the wheel-imports, image-smoke and registry gates — require the
        # driver in environments that never open a SQLite store (#2509
        # CI repair). The constructor's annotation stays a string under
        # `from __future__ import annotations`, so only this runtime
        # `aiosqlite.connect` needs the real module.
        import aiosqlite

        proof_conn = await aiosqlite.connect(path)
        try:
            await proof_conn.execute("PRAGMA busy_timeout = 0")
            try:
                await proof_conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                # `database is locked`: another writer holds the
                # transaction; its append may still commit, so no hole
                # can be judged from here. A genuine store bug (any
                # other error class) propagates instead of masquerading
                # as an inconclusive proof.
                return frozenset()
            try:
                marks = ",".join("?" * len(hole_ids))
                cursor = await proof_conn.execute(
                    f"SELECT id FROM event_log WHERE id IN ({marks})",  # nosec B608 - marks is ?-placeholders only, values bound
                    tuple(hole_ids),
                )
                visible = {int(r[0]) for r in await cursor.fetchall()}
                return frozenset(hole_ids) - visible
            finally:
                # Nothing was written: roll back to release the write
                # lock immediately rather than holding it to the next
                # statement this connection runs.
                await proof_conn.rollback()
        finally:
            await proof_conn.close()

    async def _database_path(self) -> str | None:
        """The main database's file path, or None when it is in-memory."""
        cursor = await self._conn.execute("PRAGMA database_list")
        for row in await cursor.fetchall():
            if str(row[1]) == "main":
                file_path = str(row[2] or "")
                return file_path if file_path and file_path != ":memory:" else None
        return None

    @staticmethod
    def _row_to_event(row: tuple[Any, ...]) -> LoggedEvent:
        return LoggedEvent(
            id=row[0],
            event_type=row[1],
            entity_type=row[2] or "",
            entity_id=row[3] or "",
            payload=json.loads(row[4] or "{}"),
            source=row[5] or "",
            created_at=row[6],
        )
