"""PostgreSQL persistence for the canonical BacklogItem work-source (#82).

The durable twin of `store.py`'s reference and `sqlite_store.py`, read against
the same conformance suite. What differs is not the contract but the
concurrency, and it concentrates in one rule: **at most one active claim per
item.** Two Agents calling `claim_item` concurrently must not both win, so the
claim path takes `SELECT ... FOR UPDATE` on the item row first. The lock is
not protecting the item row's contents; it is the serialisation point for the
claim decision beneath it, the same role the Workspace row lock plays in
`maistro.workspaces.pg_store`. SQLite needs no equivalent -- one writer at a
time is what a `BEGIN IMMEDIATE` buys there.

Payloads are JSONB and come back as dicts, because the pool registers a JSON
codec (`maistro.persistence._register_json_codecs`). That is why this reads
`model_of` where the SQLite store parses text, and why every statement that
binds a payload casts the parameter `$n::text::jsonb` (see `json_of`).

**No `ensure_schema`.** These tables come from Alembic migration
`058_backlog_work_source`. A store that quietly created its own would be a
second schema owner and a second thing to keep in step -- the defect migration
003 left behind and #178 had to undo. `wire_workspace_store` documents the
same refusal for Workspaces.

One transaction per decision: the item row, the claim row, and the history
event (#101) commit together, so provenance cannot drift from state across a
crash.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from maistro.backlog.cutover import AuthorityRecord, BacklogAuthority
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
    BacklogOrigin,
    status_is_terminal,
)
from maistro.backlog.store import (
    DEFAULT_LEASE_SECONDS,
    UNSET,
    _now,
    _plan_changes,
    _require_fresh_version,
    _require_valid_outcome,
)
from maistro.runs.evidence_json import decode_payload, json_of, model_of

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

#: Tables the PostgreSQL backlog store needs before it may be used.
#: Migration `058_backlog_work_source` owns them.
BACKLOG_PG_TABLES: tuple[str, ...] = (
    "backlog_items",
    "backlog_claims",
    "backlog_events",
)

#: Tables the cutover control stores (#102) need before they may be used.
#: Migration `059_backlog_authority_cutover` owns them, with the same guarded
#: DDL the SQLite twins create in `maistro.backlog.cutover`.
PG_CUTOVER_TABLES: tuple[str, ...] = (
    "backlog_authority",
    "backlog_documents",
)


class PgBacklogStore:
    """Durable BacklogItem, claim and history store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # -- reads ----------------------------------------------------------

    async def get_item(self, item_id: str) -> BacklogItem | None:
        async with self._pool.acquire() as conn:
            payload = await conn.fetchval(
                "SELECT payload FROM backlog_items WHERE item_id = $1",
                item_id,
            )
        return model_of(BacklogItem, payload) if payload is not None else None

    async def list_items(
        self,
        workspace_id: str,
        *,
        status: str | None = None,
        tag: str | None = None,
        parent_id: str | None = None,
        roots_only: bool = False,
    ) -> list[BacklogItem]:
        clauses = ["workspace_id = $1"]
        params: list[object] = [workspace_id]
        if status is not None:
            clauses.append(f"status = ${len(params) + 1}")
            params.append(status)
        if tag is not None:
            clauses.append(f"tags @> ${len(params) + 1}::jsonb")
            params.append(json.dumps([tag]))
        if parent_id is not None:
            clauses.append(f"parent_id = ${len(params) + 1}")
            params.append(parent_id)
        if roots_only:
            clauses.append("parent_id IS NULL")
        query = (
            "SELECT payload FROM backlog_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at, item_id"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [model_of(BacklogItem, row["payload"]) for row in rows]

    async def active_claim(
        self, item_id: str, *, at: datetime | None = None
    ) -> BacklogClaim | None:
        await self._require_item(item_id)
        now = _now(at)
        async with self._pool.acquire() as conn:
            claim = await self._claim_row(conn, item_id)
        if claim is not None and claim.is_active(at=now):
            return claim
        return None

    async def events(self, item_id: str) -> list[BacklogEvent]:
        await self._require_item(item_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT event_id, item_id, at, actor, kind, item_version, payload
                     FROM backlog_events WHERE item_id = $1 ORDER BY seq""",
                item_id,
            )
        return [
            BacklogEvent(
                event_id=row["event_id"],
                item_id=row["item_id"],
                at=row["at"],
                actor=row["actor"],
                kind=BacklogEventKind(row["kind"]),
                item_version=row["item_version"],
                payload=_payload_dict(row["payload"]),
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
        dependencies: tuple[str, ...] = (),
        origin: BacklogOrigin | None = None,
        priority: int = 3,
        rank: float = 1000.0,
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
            dependencies=dependencies,
            origin=origin,
            priority=priority,
            rank=rank,
            **(cast(dict[str, Any], {"item_id": item_id} if item_id is not None else {})),
        )
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT 1 FROM backlog_items WHERE item_id = $1", item.item_id
            )
            if row is not None:
                raise ValueError(f"BacklogItem {item.item_id!r} already exists")
            if parent_id is not None:
                await self._require_decomposable_parent(conn, parent_id, child=item)
            await conn.execute(
                """INSERT INTO backlog_items
                           (item_id, workspace_id, parent_id, status, tags,
                            created_at, updated_at, version, payload)
                         VALUES ($1, $2, $3, $4, $5::text::jsonb, $6, $7, $8, $9::text::jsonb)""",
                item.item_id,
                item.workspace_id,
                item.parent_id,
                item.status,
                _tags_json(item),
                item.created_at,
                item.updated_at,
                item.version,
                json_of(item),
            )
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item.item_id,
                    actor=actor,
                    kind=BacklogEventKind.CREATED,
                    item_version=item.version,
                    payload={"title": item.title, "parent_id": parent_id},
                    **(cast(dict[str, Any], {"at": at} if at is not None else {})),
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
                        **(cast(dict[str, Any], {"at": at} if at is not None else {})),
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
        status: str | None = None,
        dependencies: tuple[str, ...] | None = None,
        origin: BacklogOrigin | None | object = UNSET,
        priority: int | None = None,
        rank: float | None = None,
        at: datetime | None = None,
    ) -> BacklogItem:
        async with self._pool.acquire() as conn, conn.transaction():
            item = await self._fetch_item_for_update(conn, item_id)
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
                dependencies=dependencies,
                origin=origin,
                priority=priority,
                rank=rank,
            )
            if not changes:
                return item
            if changes.get("parent_id") is not None:
                await self._require_decomposable_parent(conn, str(changes["parent_id"]), child=item)
            updated = item.model_copy(
                update={
                    **changes,
                    "version": item.version + 1,
                    "updated_at": _now(at),
                }
            )
            # Revalidate: the model guards status/closure pairing and field shape.
            updated = BacklogItem.model_validate(updated.model_dump())
            await conn.execute(
                """UPDATE backlog_items
                          SET parent_id = $2, status = $3, tags = $4::text::jsonb,
                              updated_at = $5, version = $6, payload = $7::text::jsonb
                        WHERE item_id = $1""",
                updated.item_id,
                updated.parent_id,
                updated.status,
                _tags_json(updated),
                updated.updated_at,
                updated.version,
                json_of(updated),
            )
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=actor,
                    kind=BacklogEventKind.STATUS_CHANGED
                    if "status" in changes
                    else BacklogEventKind.UPDATED,
                    item_version=updated.version,
                    payload=_jsonable_changes(changes),
                    **(cast(dict[str, Any], {"at": at} if at is not None else {})),
                ),
            )
            return updated

    async def close_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        outcome: str,
        closure_summary: str,
        evidence_refs: tuple[str, ...],
        at: datetime | None = None,
    ) -> BacklogItem:
        async with self._pool.acquire() as conn, conn.transaction():
            item = await self._fetch_item_for_update(conn, item_id)
            _require_fresh_version(item, expected_version)
            _require_valid_outcome(outcome)
            if status_is_terminal(item.status):
                raise BacklogClosureError(item_id, f"item is already closed ({item.status})")
            try:
                closure = BacklogClosure(
                    summary=closure_summary,
                    evidence_refs=tuple(evidence_refs),
                    **({"closed_at": at} if at is not None else {}),
                )
            except ValueError as exc:
                raise BacklogClosureError(item_id, f"closure evidence incomplete: {exc}") from exc
            open_child = await conn.fetchval(
                """SELECT item_id FROM backlog_items
                        WHERE parent_id = $1 AND status NOT IN ('done', 'rejected')""",
                item_id,
            )
            if open_child is not None:
                raise BacklogClosureError(
                    item_id, f"cannot close while child {open_child!r} is still open"
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
            await self._write_item_row(conn, updated)
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=actor,
                    kind=BacklogEventKind.CLOSED,
                    item_version=updated.version,
                    payload={
                        "outcome": outcome,
                        "closure_summary": closure.summary,
                        "evidence_refs": list(closure.evidence_refs),
                    },
                    **(cast(dict[str, Any], {"at": at} if at is not None else {})),
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
        async with self._pool.acquire() as conn, conn.transaction():
            item = await self._fetch_item_for_update(conn, item_id)
            _require_fresh_version(item, expected_version)
            if not status_is_terminal(item.status):
                raise BacklogClosureError(item_id, f"item is not closed (status {item.status})")
            updated = item.model_copy(
                update={
                    "status": BacklogItemStatus.OPEN,
                    "closure": None,
                    "version": item.version + 1,
                    "updated_at": _now(at),
                }
            )
            await self._write_item_row(conn, updated)
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=actor,
                    kind=BacklogEventKind.REOPENED,
                    item_version=updated.version,
                    payload={"previous_status": item.status},
                    **(cast(dict[str, Any], {"at": at} if at is not None else {})),
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
        async with self._pool.acquire() as conn, conn.transaction():
            item = await self._fetch_item_for_update(conn, item_id)
            if status_is_terminal(item.status):
                raise BacklogClosureError(
                    item_id, f"a closed item ({item.status}) cannot be claimed"
                )
            now = _now(at)
            existing = await self._claim_row(conn, item_id)
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
                           (item_id, claim_id, claimed_by, claimed_at, lease_expires_at,
                            released_at)
                         VALUES ($1, $2, $3, $4, $5, NULL)
                         ON CONFLICT (item_id) DO UPDATE SET
                           claim_id = EXCLUDED.claim_id,
                           claimed_by = EXCLUDED.claimed_by,
                           claimed_at = EXCLUDED.claimed_at,
                           lease_expires_at = EXCLUDED.lease_expires_at,
                           released_at = NULL""",
                claim.item_id,
                claim.claim_id,
                claim.claimed_by,
                claim.claimed_at,
                claim.lease_expires_at,
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
                    **(cast(dict[str, Any], {"at": at} if at is not None else {})),
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
        async with self._pool.acquire() as conn, conn.transaction():
            item = await self._fetch_item_for_update(conn, item_id)
            now = _now(at)
            claim = await self._claim_row(conn, item_id)
            if claim is None or not claim.is_active(at=now):
                raise BacklogItemNotFound(f"no active claim on backlog item {item_id!r}")
            if claim.claim_id != claim_id:
                raise BacklogClaimError(item_id, claim)
            extended = claim.model_copy(
                update={"lease_expires_at": now + timedelta(seconds=lease_seconds)}
            )
            await conn.execute(
                "UPDATE backlog_claims SET lease_expires_at = $2 WHERE item_id = $1",
                item_id,
                extended.lease_expires_at,
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
                    **(cast(dict[str, Any], {"at": at} if at is not None else {})),
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
        async with self._pool.acquire() as conn, conn.transaction():
            item = await self._fetch_item_for_update(conn, item_id)
            now = _now(at)
            claim = await self._claim_row(conn, item_id)
            if claim is None or not claim.is_active(at=now) or claim.claim_id != claim_id:
                raise BacklogItemNotFound(
                    f"no active claim {claim_id!r} on backlog item {item_id!r}"
                )
            await conn.execute(
                "UPDATE backlog_claims SET released_at = $2 WHERE item_id = $1",
                item_id,
                now,
            )
            await self._append_event(
                conn,
                BacklogEvent(
                    item_id=item_id,
                    actor=actor,
                    kind=BacklogEventKind.CLAIM_RELEASED,
                    item_version=item.version,
                    payload={"claim_id": claim_id},
                    **(cast(dict[str, Any], {"at": at} if at is not None else {})),
                ),
            )

    # -- internals ------------------------------------------------------

    async def _require_item(self, item_id: str) -> None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 FROM backlog_items WHERE item_id = $1", item_id)
        if row is None:
            raise BacklogItemNotFound(item_id)

    async def _fetch_item_for_update(self, conn: Any, item_id: str) -> BacklogItem:
        payload = await conn.fetchval(
            "SELECT payload FROM backlog_items WHERE item_id = $1 FOR UPDATE",
            item_id,
        )
        if payload is None:
            raise BacklogItemNotFound(item_id)
        return model_of(BacklogItem, payload)

    async def _fetch_item(self, conn: Any, item_id: str) -> BacklogItem:
        payload = await conn.fetchval(
            "SELECT payload FROM backlog_items WHERE item_id = $1",
            item_id,
        )
        if payload is None:
            raise BacklogItemNotFound(item_id)
        return model_of(BacklogItem, payload)

    async def _claim_row(self, conn: Any, item_id: str) -> BacklogClaim | None:
        row = await conn.fetchrow(
            """SELECT item_id, claim_id, claimed_by, claimed_at, lease_expires_at, released_at
                 FROM backlog_claims WHERE item_id = $1""",
            item_id,
        )
        if row is None:
            return None
        return BacklogClaim(
            item_id=row["item_id"],
            claim_id=row["claim_id"],
            claimed_by=row["claimed_by"],
            claimed_at=row["claimed_at"],
            lease_expires_at=row["lease_expires_at"],
            released_at=row["released_at"],
        )

    @staticmethod
    async def _write_item_row(conn: Any, item: BacklogItem) -> None:
        await conn.execute(
            """UPDATE backlog_items
                  SET status = $2, tags = $3::text::jsonb, updated_at = $4,
                      version = $5, payload = $6::text::jsonb
                WHERE item_id = $1""",
            item.item_id,
            item.status,
            _tags_json(item),
            item.updated_at,
            item.version,
            json_of(item),
        )

    @staticmethod
    async def _append_event(conn: Any, event: BacklogEvent) -> None:
        await conn.execute(
            """INSERT INTO backlog_events
                   (event_id, item_id, at, actor, kind, item_version, payload)
                 VALUES ($1, $2, $3, $4, $5, $6, $7::text::jsonb)""",
            event.event_id,
            event.item_id,
            event.at,
            event.actor,
            event.kind.value,
            event.item_version,
            json.dumps(event.payload),
        )

    async def _require_decomposable_parent(
        self, conn: Any, parent_id: str, *, child: BacklogItem
    ) -> None:
        # Lock the parent with FOR UPDATE so attaching a child serializes
        # against close_item on the same row; otherwise a concurrent close
        # could see no open child while this transaction still sees the
        # parent open, committing a terminal parent with an open child.
        parent = await self._fetch_item_for_update(conn, parent_id)
        if parent.workspace_id != child.workspace_id:
            raise ValueError("a child item must live in its parent's Workspace")
        if status_is_terminal(parent.status):
            raise BacklogClosureError(parent_id, "cannot decompose a closed item")
        walker = parent
        seen: set[str] = set()
        while walker.parent_id is not None and walker.parent_id not in seen:
            if walker.parent_id == child.item_id:
                raise ValueError("decomposition would create a parent/child cycle")
            seen.add(walker.parent_id)
            walker = await self._fetch_item(conn, walker.parent_id)


def _tags_json(item: BacklogItem) -> str:
    return json.dumps(list(item.tags))


def _payload_dict(payload: object) -> dict[str, object]:
    """Event payload as a dict, whichever shape the pool's jsonb codec yields.

    `maistro.persistence.get_pool` registers a JSON codec, so a pooled read
    returns a dict; a raw `asyncpg.create_pool` (conformance tests, tools)
    leaves the default `str` codec in place and returns text. Accept both.
    """
    if isinstance(payload, str):
        decoded: object = json.loads(payload)
        if isinstance(decoded, dict):
            return decoded
        msg = f"backlog event payload text must decode to an object, got {type(decoded).__name__}"
        raise TypeError(msg)
    if isinstance(payload, dict):
        return dict(payload)
    msg = f"backlog event payload must be jsonb text or a decoded object, got {type(payload).__name__}"
    raise TypeError(msg)


def _jsonable_changes(changes: dict[str, object]) -> dict[str, object]:
    """Event-payload form of a change plan.

    Item statuses are boundary-validated plain strings (#101 convention), so
    the plan is already payload-shaped; the copy keeps callers from sharing
    the mutable event payload with the change plan.
    """
    return dict(changes)


async def _require_tables(pool: asyncpg.Pool, tables: tuple[str, ...], migration: str) -> None:
    """Refuse to run against a database the owning migration has not touched.

    The DDL belongs to Alembic alone (see the module docstring), so instead of
    quietly creating anything the stores probe for their tables and name the
    migration that must run — an operator mistake made explicit beats a second
    schema owner.
    """
    missing = [
        table
        for table in tables
        if not await pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
    ]
    if missing:
        msg = (
            f"PostgreSQL database is missing the backlog tables ({', '.join(missing)}); "
            f"run `alembic upgrade {migration}` against it before using these stores"
        )
        raise RuntimeError(msg)


class PgAuthorityLedger:
    """The authority ledger on the Alembic-managed `backlog_authority` table.

    The durable twin of `SqliteAuthorityLedger`, reading the same
    `AuthorityRecord` rows. Appends are one `INSERT ... RETURNING`, so the
    revision the BIGSERIAL assigned and the row it annotates come back from a
    single statement — no lock and no read-after-write window to lose a race
    in, which is what the SQLite twin's `BEGIN IMMEDIATE` buys there.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await _require_tables(self._pool, PG_CUTOVER_TABLES, "head")

    async def current(self) -> AuthorityRecord | None:
        row = await self._pool.fetchrow(
            "SELECT revision, authority, actor, at, note FROM backlog_authority "
            "ORDER BY revision DESC LIMIT 1"
        )
        return AuthorityRecord.from_row(row) if row is not None else None

    async def append(
        self,
        *,
        authority: BacklogAuthority,
        actor: str,
        note: str,
        at: datetime | None = None,
    ) -> AuthorityRecord:
        row = await self._pool.fetchrow(
            "INSERT INTO backlog_authority (authority, actor, at, note) "
            "VALUES ($1, $2, $3, $4) "
            "RETURNING revision, authority, actor, at, note",
            authority.value,
            actor,
            _now(at),
            note,
        )
        if row is None:  # pragma: no cover - RETURNING always yields the row
            msg = "authority append did not persist"
            raise RuntimeError(msg)
        return AuthorityRecord.from_row(row)

    async def history(self) -> list[AuthorityRecord]:
        rows = await self._pool.fetch(
            "SELECT revision, authority, actor, at, note FROM backlog_authority "
            "ORDER BY revision ASC"
        )
        return [AuthorityRecord.from_row(row) for row in rows]


class PgDocumentState:
    """The token-stream store on the Alembic-managed `backlog_documents` table.

    The durable twin of `SqliteDocumentState`; the JSONB column carries the
    same `[[kind, value], ...]` shape, read back through the pool's JSON codec
    (`maistro.persistence._register_json_codecs`).
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await _require_tables(self._pool, PG_CUTOVER_TABLES, "head")

    async def get_tokens(self, document_id: str) -> tuple[tuple[str, str], ...] | None:
        row = await self._pool.fetchrow(
            "SELECT tokens FROM backlog_documents WHERE document_id = $1",
            document_id,
        )
        if row is None:
            return None
        return _token_pairs(row[0])

    async def put_tokens(self, document_id: str, tokens: Sequence[tuple[str, str]]) -> None:
        payload = json.dumps([[kind, value] for kind, value in tokens])
        await self._pool.execute(
            "INSERT INTO backlog_documents (document_id, tokens, updated_at) "
            "VALUES ($1, $2::text::jsonb, $3) "
            "ON CONFLICT (document_id) DO UPDATE "
            "SET tokens = excluded.tokens, updated_at = excluded.updated_at",
            document_id,
            payload,
            _now(None),
        )


def _token_pairs(payload: object) -> tuple[tuple[str, str], ...]:
    """Stored document tokens as pairs, however the driver handed them over.

    The same pool-independence rule `decode_payload` states for spine payloads:
    `maistro.persistence.get_pool` registers a JSON codec, so a pooled read of
    the jsonb `tokens` column returns the decoded array, while a raw
    `asyncpg.create_pool` (conformance tests, tools) leaves the default `str`
    codec in place and returns text. A store whose correctness depends on how
    somebody else constructed the pool is the hidden coupling
    `pg_learnings._load_keys` names — decode defensively and be right either
    way.
    """
    decoded = decode_payload(payload)
    if not isinstance(decoded, list):
        msg = f"backlog document tokens must be a jsonb array, got {type(decoded).__name__}"
        raise TypeError(msg)
    return tuple((str(kind), str(value)) for kind, value in decoded)


__all__ = [
    "BACKLOG_PG_TABLES",
    "PG_CUTOVER_TABLES",
    "PgAuthorityLedger",
    "PgBacklogStore",
    "PgDocumentState",
]
