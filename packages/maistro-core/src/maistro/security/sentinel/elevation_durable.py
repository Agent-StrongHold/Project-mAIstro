"""Durable elevation-grant stores for the supported relational backends."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.persistence.sqlite_schema import begin_schema_upgrade
from maistro.security.sentinel.elevation import ElevationGrant, ElevationStore

if TYPE_CHECKING:
    import aiosqlite


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS elevation_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    principal_id TEXT NOT NULL,
    action_class TEXT NOT NULL,
    kind TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    signed_by TEXT NOT NULL,
    action_args_hash TEXT
)
"""


class SqliteElevationStore(ElevationStore):
    """SQLite elevation store; proofs are not persisted, only grant facts."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        await begin_schema_upgrade(self._conn)
        await self._conn.execute(_SQLITE_SCHEMA)
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_elevation_grants_lookup "
            "ON elevation_grants (principal_id, action_class, granted_at)"
        )
        await self._conn.commit()

    async def store(self, grant: ElevationGrant) -> None:
        await self._conn.execute(
            "INSERT INTO elevation_grants "
            "(principal_id, action_class, kind, granted_at, ttl_seconds, signed_by, action_args_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                grant.principal_id,
                grant.action_class,
                grant.kind,
                grant.granted_at.isoformat(),
                grant.ttl_seconds,
                grant.signed_by,
                grant.action_args_hash,
            ),
        )
        await self._conn.commit()

    async def find_valid(
        self, principal_id: str, action_class: str, args_hash: str | None
    ) -> ElevationGrant | None:
        cursor = await self._conn.execute(
            "SELECT principal_id, action_class, kind, granted_at, ttl_seconds, signed_by, "
            "action_args_hash FROM elevation_grants "
            "WHERE principal_id = ? AND action_class = ? "
            "ORDER BY id DESC",
            (principal_id, action_class),
        )
        now = datetime.now(UTC)
        for row in await cursor.fetchall():
            grant = _grant_from_row(row)
            if grant.is_valid(now=now, action_class=action_class, args_hash=args_hash):
                return grant
        return None


def _grant_from_row(row: Any) -> ElevationGrant:
    timestamp = datetime.fromisoformat(str(row[3]))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return ElevationGrant(
        principal_id=str(row[0]),
        action_class=str(row[1]),
        kind=str(row[2]),  # type: ignore[arg-type]
        granted_at=timestamp,
        ttl_seconds=int(row[4]),
        signed_by=str(row[5]),
        action_args_hash=row[6],
    )


class PgElevationStore(ElevationStore):
    """PostgreSQL elevation store using the container's canonical pool."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def store(self, grant: ElevationGrant) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO elevation_grants "
                "(principal_id, action_class, kind, granted_at, ttl_seconds, signed_by, action_args_hash) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                grant.principal_id,
                grant.action_class,
                grant.kind,
                grant.granted_at,
                grant.ttl_seconds,
                grant.signed_by,
                grant.action_args_hash,
            )

    async def find_valid(
        self, principal_id: str, action_class: str, args_hash: str | None
    ) -> ElevationGrant | None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT principal_id, action_class, kind, granted_at, ttl_seconds, signed_by, "
                "action_args_hash FROM elevation_grants "
                "WHERE principal_id = $1 AND action_class = $2 "
                "ORDER BY id DESC",
                principal_id,
                action_class,
            )
        now = datetime.now(UTC)
        for row in rows:
            grant = ElevationGrant(
                principal_id=row["principal_id"],
                action_class=row["action_class"],
                kind=row["kind"],
                granted_at=row["granted_at"],
                ttl_seconds=row["ttl_seconds"],
                signed_by=row["signed_by"],
                action_args_hash=row["action_args_hash"],
            )
            if grant.is_valid(now=now, action_class=action_class, args_hash=args_hash):
                return grant
        return None


async def build_elevation_store(*, pg_pool: Any, db_pool: Any) -> ElevationStore:
    """Select elevation persistence from the same backend as the other stores."""
    if pg_pool is not None:
        return PgElevationStore(pg_pool)
    if db_pool is not None:
        store = SqliteElevationStore(db_pool)
        await store.ensure_schema()
        return store
    from maistro.security.sentinel.elevation import InMemoryElevationStore

    return InMemoryElevationStore()
