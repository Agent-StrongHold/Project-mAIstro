"""SQLite persistence for the canonical BacklogItem work-source (#82).

The durable twin of `store.py`'s reference, read against the same conformance
suite. Two things differ from the reference, and both are about what SQLite
already guarantees:

**Serialisation.** "At most one active claim per item" is a check-then-set in
the reference, correct in one event loop and wrong across processes. SQLite
allows one writer at a time, so every write runs inside one `BEGIN IMMEDIATE`
-- the write lock is taken before the claim row is read, and a second writer
waits rather than reading a claim that is about to change. An `asyncio.Lock`
orders same-process writers so an `await` inside a write cannot interleave
two `BEGIN IMMEDIATE`s on the one connection ("cannot start a transaction
within a transaction").

**One transaction per decision.** The item row, its claim row, and the
history event a mutation appends (#101) commit together or not at all: a
state change whose provenance did not survive the crash is a silently
unattributed change, which is the drift the event log exists to prevent.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from maistro.backlog.model import (
    BacklogClaim,
    BacklogClaimError,
    BacklogClosure,
    BacklogClosureError,
    BacklogEvent,
    BacklogEventKind,
    BacklogItem,
    BacklogItemNotFound,
    BacklogItemStatus,
)
from maistro.backlog.store import (
    DEFAULT_LEASE_SECONDS,
    UNSET,
    _now,
    _plan_changes,
    _require_fresh_version,
    _require_valid_outcome,
)
from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS backlog_items (
    item_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    parent_id TEXT,
    status TEXT NOT NULL,
    tags TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_backlog_items_workspace
    ON backlog_items(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_backlog_items_children
    ON backlog_items(parent_id);

CREATE TABLE IF NOT EXISTS backlog_claims (
    item_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    claimed_by TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    released_at TEXT
);

CREATE TABLE IF NOT EXISTS backlog_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    item_version INTEGER NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_backlog_events_item
    ON backlog_events(item_id, seq);
"""


class SqliteBacklogStore:
    """Durable BacklogItem, claim and history store for a single instance."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create the backlog tables and their indexes."""
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SCHEMA)

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[aiosqlite.Connection]:
        """The one write-critical section: `BEGIN IMMEDIATE`, yield, commit.

        Rolls back on any failure, so an item mutation and its event row are
        never observed apart.
        """
        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                await self._conn.rollback()
                raise
            else:
                await self._conn.commit()

    # -- reads ----------------------------------------------------------
    # Reads take `_write_lock` too: the store uses one shared connection, so
    # an unguarded read would run *inside* another task's open write
    # transaction (aiosqlite interleaves per statement) and could observe an
    # item mutation before its provenance event is appended.

    async def get_item(self, item_id: str) -> BacklogItem | None:
        async with (
            self._write_lock,
            self._conn.execute(
                "SELECT payload FROM backlog_items WHERE item_id = ?",
                (item_id,),
            ) as cursor,
        ):
            row = await cursor.fetchone()
        return BacklogItem.model_validate_json(row[0]) if row is not None else None

    async def list_items(
        self,
        workspace_id: str,
        *,
        status: BacklogItemStatus | None = None,
        tag: str | None = None,
        parent_id: str | None = None,
        roots_only: bool = False,
    ) -> list[BacklogItem]:
        clauses = ["workspace_id = ?"]
        params: list[object] = [workspace_id]
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if tag is not None:
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        if parent_id is not None:
            clauses.append("parent_id = ?")
            params.append(parent_id)
        if roots_only:
            clauses.append("parent_id IS NULL")
        query = (
            "SELECT payload FROM backlog_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at, item_id"
        )
        async with self._write_lock, self._conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return [BacklogItem.model_validate_json(row[0]) for row in rows]

    async def active_claim(
        self, item_id: str, *, at: datetime | None = None
    ) -> BacklogClaim | None:
        async with self._write_lock:
            await self._require_item(item_id)
            now = _now(at)
            claim = await self._claim_row(item_id)
            if claim is not None and claim.is_active(at=now):
                return claim
        return None

    async def events(self, item_id: str) -> list[BacklogEvent]:
        async with self._write_lock:
            await self._require_item(item_id)
            async with self._conn.execute(
                """SELECT event_id, item_id, at, actor, kind, item_version, payload
                     FROM backlog_events WHERE item_id = ? ORDER BY seq""",
                (item_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            BacklogEvent(
                event_id=row[0],
                item_id=row[1],
                at=datetime.fromisoformat(row[2]),
                actor=row[3],
                kind=BacklogEventKind(row[4]),
                item_version=row[5],
                payload=json.loads(row[6]),
            )
            for row in rows
        ]

    # -- writes ---------------------------------------------------------

    async def create_item(
        self,
        *,
        workspace_id: str,
        title: str,
        actor: str,
        details: str = "",
        tags: tuple[str, ...] = (),
        milestone: str | None = None,
        package: str | None = None,
        risk_notes: str = "",
        parent_id: str | None = None,
        goal_id: str | None = None,
        goal_revision: int | None = None,
        source: str = "human",
        item_id: str | None = None,
        at: datetime | None = None,
    ) -> BacklogItem:
        item = BacklogItem(
            workspace_id=workspace_id,
            title=title,
            created_by=actor,
            details=details,
            tags=tags,
            milestone=milestone,
            package=package,
            risk_notes=risk_notes,
            parent_id=parent_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            source=source,
            **({"item_id": item_id} if item_id is not None else {}),
        )
        async with self._write() as conn:
            if await self._item_row_exists(conn, item.item_id):
                raise ValueError(f"BacklogItem {item.item_id!r} already exists")
            if parent_id is not None:
                await self._require_decomposable_parent(conn, parent_id, child=item)
            await self._insert_item(conn, item)
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item.item_id,
                    actor=actor,
                    kind=BacklogEventKind.CREATED,
                    item_version=item.version,
                    payload={"title": item.title, "parent_id": parent_id},
                    **({"at": at} if at is not None else {}),
                ),
            )
            if parent_id is not None:
                parent = await self._fetch_item(conn, parent_id)
                await self._append_event(
                    conn,
                    BacklogEvent(
                        item_id=parent_id,
                        actor=actor,
                        kind=BacklogEventKind.DECOMPOSED,
                        item_version=parent.version,
                        payload={"child_id": item.item_id, "child_title": item.title},
                        **({"at": at} if at is not None else {}),
                    ),
                )
        return item

    async def update_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        title: str | None = None,
        details: str | None = None,
        risk_notes: str | None = None,
        tags: tuple[str, ...] | None = None,
        milestone: str | None | object = UNSET,
        package: str | None | object = UNSET,
        parent_id: str | None | object = UNSET,
        goal_id: str | None | object = UNSET,
        goal_revision: int | None | object = UNSET,
        status: BacklogItemStatus | None = None,
        at: datetime | None = None,
    ) -> BacklogItem:
        async with self._write() as conn:
            item = await self._fetch_item(conn, item_id)
            _require_fresh_version(item, expected_version)
            changes = _plan_changes(
                item,
                title=title,
                details=details,
                risk_notes=risk_notes,
                tags=tags,
                milestone=milestone,
                package=package,
                parent_id=parent_id,
                goal_id=goal_id,
                goal_revision=goal_revision,
                status=status,
            )
            if not changes:
                return item
            if changes.get("parent_id") is not None:
                await self._require_decomposable_parent(conn, str(changes["parent_id"]), child=item)
            updated = await _apply_changes(conn, item, changes, at=at)
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=actor,
                    kind=BacklogEventKind.STATUS_CHANGED
                    if "status" in changes
                    else BacklogEventKind.UPDATED,
                    item_version=updated.version,
                    payload=dict(changes.items()),
                    **({"at": at} if at is not None else {}),
                ),
            )
            return updated

    async def close_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        outcome: BacklogItemStatus,
        closure_summary: str,
        evidence_refs: tuple[str, ...],
        at: datetime | None = None,
    ) -> BacklogItem:
        async with self._write() as conn:
            item = await self._fetch_item(conn, item_id)
            _require_fresh_version(item, expected_version)
            _require_valid_outcome(outcome)
            if item.status.is_terminal:
                raise BacklogClosureError(item_id, f"item is already closed ({item.status.value})")
            try:
                closure = BacklogClosure(
                    summary=closure_summary,
                    evidence_refs=tuple(evidence_refs),
                    **({"closed_at": at} if at is not None else {}),
                )
            except ValueError as exc:
                raise BacklogClosureError(item_id, f"closure evidence incomplete: {exc}") from exc
            async with conn.execute(
                "SELECT item_id FROM backlog_items WHERE parent_id = ? AND status != 'done' AND status != 'rejected'",
                (item_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is not None:
                raise BacklogClosureError(
                    item_id, f"cannot close while child {row[0]!r} is still open"
                )
            closed_at = _now(at)
            updated = item.model_copy(
                update={
                    "status": outcome,
                    "closure": closure,
                    "version": item.version + 1,
                    "updated_at": closed_at,
                }
            )
            await self._write_item(conn, updated)
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=actor,
                    kind=BacklogEventKind.CLOSED,
                    item_version=updated.version,
                    payload={
                        "outcome": outcome.value,
                        "closure_summary": closure.summary,
                        "evidence_refs": list(closure.evidence_refs),
                    },
                    **({"at": at} if at is not None else {}),
                ),
            )
            return updated

    async def reopen_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        at: datetime | None = None,
    ) -> BacklogItem:
        async with self._write() as conn:
            item = await self._fetch_item(conn, item_id)
            _require_fresh_version(item, expected_version)
            if not item.status.is_terminal:
                raise BacklogClosureError(
                    item_id, f"item is not closed (status {item.status.value})"
                )
            updated = item.model_copy(
                update={
                    "status": BacklogItemStatus.OPEN,
                    "closure": None,
                    "version": item.version + 1,
                    "updated_at": _now(at),
                }
            )
            await self._write_item(conn, updated)
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=actor,
                    kind=BacklogEventKind.REOPENED,
                    item_version=updated.version,
                    payload={"previous_status": item.status.value},
                    **({"at": at} if at is not None else {}),
                ),
            )
            return updated

    async def claim_item(
        self,
        item_id: str,
        *,
        claimed_by: str,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        at: datetime | None = None,
    ) -> BacklogClaim:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        async with self._write() as conn:
            item = await self._fetch_item(conn, item_id)
            if item.status.is_terminal:
                raise BacklogClosureError(
                    item_id, f"a closed item ({item.status.value}) cannot be claimed"
                )
            now = _now(at)
            existing = await self._claim_row(item_id)
            if existing is not None and existing.is_active(at=now):
                raise BacklogClaimError(item_id, existing)
            claim = BacklogClaim(
                item_id=item_id,
                claimed_by=claimed_by,
                claimed_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            await conn.execute(
                """INSERT INTO backlog_claims
                       (item_id, claim_id, claimed_by, claimed_at, lease_expires_at, released_at)
                     VALUES (?, ?, ?, ?, ?, NULL)
                     ON CONFLICT (item_id) DO UPDATE SET
                       claim_id = excluded.claim_id,
                       claimed_by = excluded.claimed_by,
                       claimed_at = excluded.claimed_at,
                       lease_expires_at = excluded.lease_expires_at,
                       released_at = NULL""",
                (
                    claim.item_id,
                    claim.claim_id,
                    claim.claimed_by,
                    claim.claimed_at.isoformat(),
                    claim.lease_expires_at.isoformat(),
                ),
            )
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=claimed_by,
                    kind=BacklogEventKind.CLAIMED,
                    item_version=item.version,
                    payload={
                        "claim_id": claim.claim_id,
                        "lease_expires_at": claim.lease_expires_at.isoformat(),
                    },
                    **({"at": at} if at is not None else {}),
                ),
            )
            return claim

    async def extend_claim(
        self,
        item_id: str,
        *,
        claim_id: str,
        lease_seconds: float,
        actor: str,
        at: datetime | None = None,
    ) -> BacklogClaim:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        async with self._write() as conn:
            item = await self._fetch_item(conn, item_id)
            now = _now(at)
            claim = await self._claim_row(item_id)
            if claim is None or not claim.is_active(at=now):
                raise BacklogItemNotFound(f"no active claim on backlog item {item_id!r}")
            if claim.claim_id != claim_id:
                raise BacklogClaimError(item_id, claim)
            extended = claim.model_copy(
                update={"lease_expires_at": now + timedelta(seconds=lease_seconds)}
            )
            await conn.execute(
                "UPDATE backlog_claims SET lease_expires_at = ? WHERE item_id = ?",
                (extended.lease_expires_at.isoformat(), item_id),
            )
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=actor,
                    kind=BacklogEventKind.LEASE_EXTENDED,
                    item_version=item.version,
                    payload={
                        "claim_id": claim_id,
                        "lease_expires_at": extended.lease_expires_at.isoformat(),
                    },
                    **({"at": at} if at is not None else {}),
                ),
            )
            return extended

    async def release_claim(
        self,
        item_id: str,
        *,
        claim_id: str,
        actor: str,
        at: datetime | None = None,
    ) -> None:
        async with self._write() as conn:
            item = await self._fetch_item(conn, item_id)
            now = _now(at)
            claim = await self._claim_row(item_id)
            if claim is None or not claim.is_active(at=now) or claim.claim_id != claim_id:
                raise BacklogItemNotFound(
                    f"no active claim {claim_id!r} on backlog item {item_id!r}"
                )
            await conn.execute(
                "UPDATE backlog_claims SET released_at = ? WHERE item_id = ?",
                (now.isoformat(), item_id),
            )
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=actor,
                    kind=BacklogEventKind.CLAIM_RELEASED,
                    item_version=item.version,
                    payload={"claim_id": claim_id},
                    **({"at": at} if at is not None else {}),
                ),
            )

    # -- internals ------------------------------------------------------

    async def _require_item(self, item_id: str) -> None:
        if not await self._item_row_exists(self._conn, item_id):
            raise BacklogItemNotFound(item_id)

    async def _claim_row(self, item_id: str) -> BacklogClaim | None:
        async with self._conn.execute(
            """SELECT item_id, claim_id, claimed_by, claimed_at, lease_expires_at, released_at
                 FROM backlog_claims WHERE item_id = ?""",
            (item_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return BacklogClaim(
            item_id=row[0],
            claim_id=row[1],
            claimed_by=row[2],
            claimed_at=datetime.fromisoformat(row[3]),
            lease_expires_at=datetime.fromisoformat(row[4]),
            released_at=datetime.fromisoformat(row[5]) if row[5] is not None else None,
        )

    async def _fetch_item(self, conn: aiosqlite.Connection, item_id: str) -> BacklogItem:
        async with conn.execute(
            "SELECT payload FROM backlog_items WHERE item_id = ?", (item_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise BacklogItemNotFound(item_id)
        return BacklogItem.model_validate_json(row[0])

    async def _item_row_exists(self, conn: aiosqlite.Connection, item_id: str) -> bool:
        async with conn.execute(
            "SELECT 1 FROM backlog_items WHERE item_id = ?", (item_id,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def _insert_item(self, conn: aiosqlite.Connection, item: BacklogItem) -> None:
        await conn.execute(
            """INSERT INTO backlog_items
                   (item_id, workspace_id, parent_id, status, tags,
                    created_at, updated_at, version, payload)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.item_id,
                item.workspace_id,
                item.parent_id,
                item.status.value,
                json.dumps(list(item.tags)),
                item.created_at.isoformat(),
                item.updated_at.isoformat(),
                item.version,
                item.model_dump_json(),
            ),
        )

    async def _write_item(self, conn: aiosqlite.Connection, item: BacklogItem) -> None:
        await conn.execute(
            """UPDATE backlog_items
                  SET status = ?, tags = ?, updated_at = ?, version = ?, payload = ?
                WHERE item_id = ?""",
            (
                item.status.value,
                json.dumps(list(item.tags)),
                item.updated_at.isoformat(),
                item.version,
                item.model_dump_json(),
                item.item_id,
            ),
        )

    async def _append_event(self, conn: aiosqlite.Connection, event: BacklogEvent) -> None:
        await conn.execute(
            """INSERT INTO backlog_events
                   (event_id, item_id, at, actor, kind, item_version, payload)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.item_id,
                event.at.isoformat(),
                event.actor,
                event.kind.value,
                event.item_version,
                json.dumps(event.payload),
            ),
        )

    async def _require_decomposable_parent(
        self, conn: aiosqlite.Connection, parent_id: str, *, child: BacklogItem
    ) -> None:
        parent = await self._fetch_item(conn, parent_id)
        if parent.workspace_id != child.workspace_id:
            raise ValueError("a child item must live in its parent's Workspace")
        if parent.status.is_terminal:
            raise BacklogClosureError(parent_id, "cannot decompose a closed item")
        walker = parent
        seen: set[str] = set()
        while walker.parent_id is not None and walker.parent_id not in seen:
            if walker.parent_id == child.item_id:
                raise ValueError("decomposition would create a parent/child cycle")
            seen.add(walker.parent_id)
            walker = await self._fetch_item(conn, walker.parent_id)


async def _apply_changes(
    conn: aiosqlite.Connection,
    item: BacklogItem,
    changes: dict[str, object],
    *,
    at: datetime | None,
) -> BacklogItem:
    updated = item.model_copy(
        update={
            **changes,
            "version": item.version + 1,
            "updated_at": _now(at),
        }
    )
    # Revalidate: the model guards status/closure pairing and field shape.
    updated = BacklogItem.model_validate(updated.model_dump())
    # Keep the filter/order columns in step with the payload, or `list_items`
    # would answer from a status or hierarchy the payload no longer holds.
    await conn.execute(
        """UPDATE backlog_items
              SET parent_id = ?, status = ?, tags = ?, updated_at = ?, version = ?, payload = ?
            WHERE item_id = ?""",
        (
            updated.parent_id,
            updated.status.value,
            json.dumps(list(updated.tags)),
            updated.updated_at.isoformat(),
            updated.version,
            updated.model_dump_json(),
            updated.item_id,
        ),
    )
    return updated


__all__ = ["SqliteBacklogStore"]
