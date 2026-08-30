"""SQLite episodic memory store — the homelab twin of `PgEpisodicStore`.

Same protocols, same row mapping (`episodic_rows`), same scope rule compiled
from `maistro.memory.scopes`. What differs is only what the driver requires:
`?` markers instead of `$n`, text for JSON and timestamps, and a `CREATE TABLE`
of its own because `alembic/versions/` describes the PostgreSQL schema
(ADR-083026-a322).
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.memory.episodic.ranking import rank
from maistro.memory.episodic.tiers import clamp_weight
from maistro.memory.episodic.tiers import reinforce as _reinforce
from maistro.memory.episodic.tiers import tick_decay as _tick_decay
from maistro.memory.scopes import build_scope_filter, scope_predicate
from maistro.persistence.episodic_rows import (
    COLUMNS,
    RETRIEVAL_CANDIDATE_CAP,
    from_row,
    to_row,
)
from maistro.types.memory import DecaySweep, EpisodicMemory

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodic_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL DEFAULT 'observation',
    content TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL DEFAULT 0.3,
    org_id TEXT NOT NULL DEFAULT '',
    team_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT,
    user_id TEXT,
    scope TEXT NOT NULL DEFAULT 'agent',
    project_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '{}',
    reinforcement_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    last_accessed_at TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0,
    decay_rate REAL NOT NULL DEFAULT 0.01,
    shared INTEGER NOT NULL DEFAULT 0,
    flagged_for_review INTEGER NOT NULL DEFAULT 0
)
"""

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM episodic_memories"


def _mapped(cursor: Any, row: Any) -> dict[str, Any]:
    """One row as a name-keyed mapping, so `from_row` can read it.

    Built from `cursor.description` rather than by setting
    `Connection.row_factory`: the connection belongs to the caller, and a store
    that reconfigures it changes how every other store sharing it reads.
    """
    return dict(zip([column[0] for column in cursor.description], row, strict=True))


class SqliteEpisodicStore:
    """SQLite-backed episodic store: `EpisodicStore` + `DecayableEpisodicStore`."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        """Create the table, and upgrade one created before the record's fields.

        SQLite has no `ADD COLUMN IF NOT EXISTS`, so the column list is
        inspected first — the same shape `SqliteLearningStore.ensure_schema`
        uses, and for the same reason: `ALTER TABLE ... ADD COLUMN` with a
        constant default is metadata-only, so this is cheap.
        """
        await self._conn.execute(_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(episodic_memories)")
        present = {row[1] for row in await cursor.fetchall()}
        for column, ddl in (
            ("project_id", "TEXT NOT NULL DEFAULT ''"),
            ("decay_rate", "REAL NOT NULL DEFAULT 0.01"),
            ("shared", "INTEGER NOT NULL DEFAULT 0"),
            ("flagged_for_review", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in present:
                await self._conn.execute(f"ALTER TABLE episodic_memories ADD COLUMN {column} {ddl}")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_scope_weight "
            "ON episodic_memories (org_id, scope, weight DESC)"
        )
        await self._conn.commit()

    async def store(self, memory: EpisodicMemory) -> str:
        """Store a memory. Returns its `memory_id`. Upsert, as in PostgreSQL."""
        assignments = ", ".join(f"{name} = excluded.{name}" for name in COLUMNS[1:])
        await self._conn.execute(
            f"INSERT INTO episodic_memories ({', '.join(COLUMNS)})"
            f" VALUES ({', '.join('?' * len(COLUMNS))})"
            f" ON CONFLICT (memory_id) DO UPDATE SET {assignments}",
            to_row(memory, text_encoded=True),
        )
        await self._conn.commit()
        return memory.memory_id

    async def _fetch(self, sql: str, params: tuple[Any, ...]) -> list[EpisodicMemory]:
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [from_row(_mapped(cursor, row)) for row in rows]

    async def retrieve(
        self,
        query: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Rank the scope-matching live memories against `query`."""
        predicate, params = scope_predicate(
            build_scope_filter(agent_id=agent_id, user_id=user_id, team_id=team_id, org_id=org_id),
            itertools.repeat("?"),
        )
        candidates = await self._fetch(
            f"{_SELECT} WHERE deleted = 0 AND ({predicate})"
            " ORDER BY weight DESC, memory_id LIMIT ?",
            (*params, RETRIEVAL_CANDIDATE_CAP),
        )
        return rank(query, candidates, k=limit)

    async def reinforce(self, memory_id: str, delta: float = 0.05) -> None:
        """Raise a memory's weight, clamped to its tier ceiling."""
        found = await self._fetch(f"{_SELECT} WHERE memory_id = ?", (memory_id,))
        if not found:
            return
        updated = _reinforce(found[0], delta)
        await self._conn.execute(
            "UPDATE episodic_memories SET weight = ?, reinforcement_count = ? WHERE memory_id = ?",
            (updated.weight, updated.reinforcement_count, memory_id),
        )
        await self._conn.commit()

    async def apply_decay(self, *, now: datetime | None = None) -> DecaySweep:
        """Decay every live memory once, reporting what the sweep touched."""
        moment = now or datetime.now(UTC)
        scanned = decayed = at_floor = 0
        for memory in await self._fetch(f"{_SELECT} WHERE deleted = 0", ()):
            floor = clamp_weight(memory.tier, float("-inf"))
            swept = _tick_decay(memory, now=moment)
            await self._conn.execute(
                "UPDATE episodic_memories SET weight = ?, last_accessed_at = ? WHERE memory_id = ?",
                (swept.weight, swept.last_accessed_at.isoformat(), memory.memory_id),
            )
            scanned += 1
            decayed += swept.weight != memory.weight
            at_floor += swept.weight <= floor
        await self._conn.commit()
        return DecaySweep(scanned=scanned, decayed=decayed, at_floor=at_floor)

    async def list_by_scope(
        self,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        project_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 50,
    ) -> list[EpisodicMemory]:
        """Scope-filtered memories at or above `min_weight`, heaviest first."""
        params: list[Any] = []
        clauses = ["deleted = 0"]
        if agent_id or user_id or team_id or org_id:
            predicate, scope_params = scope_predicate(
                build_scope_filter(
                    agent_id=agent_id, user_id=user_id, team_id=team_id, org_id=org_id
                ),
                itertools.repeat("?"),
            )
            clauses.append(f"({predicate})")
            params.extend(scope_params)
        clauses.append("weight >= ?")
        params.append(min_weight)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        params.append(limit)
        return await self._fetch(
            f"{_SELECT} WHERE {' AND '.join(clauses)} ORDER BY weight DESC, memory_id LIMIT ?",
            tuple(params),
        )
