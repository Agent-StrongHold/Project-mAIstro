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
from maistro.observability.correlation import observed_provenance
from maistro.persistence.episodic_rows import (
    COLUMNS,
    RETRIEVAL_CANDIDATE_CAP,
    from_row,
    to_row,
)
from maistro.types.memory import REINFORCE_DELTA, DecaySweep, EpisodicMemory

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
    flagged_for_review INTEGER NOT NULL DEFAULT 0,
    run_id TEXT,
    node_run_id TEXT,
    attempt_id TEXT
)
"""

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM episodic_memories"

#: The upsert, written out rather than assembled from `COLUMNS`.
#:
#: Bandit's B608 fires on any SQL built by string formatting and this repo runs
#: it at a strict zero baseline, so the choice is a literal statement or a
#: `# nosec` on an injection warning. A literal is the better answer: it is
#: greppable, and `test_the_insert_matches_the_column_list` fails if it ever
#: drifts from `COLUMNS`, which is the only property the assembled version
#: actually bought.
_UPSERT = """INSERT INTO episodic_memories (
    memory_id, tier, content, weight, org_id, team_id, agent_id, user_id,
    scope, project_id, source, context, reinforcement_count,
    contradiction_count, created_at, last_accessed_at, deleted, decay_rate,
    shared, flagged_for_review, run_id, node_run_id, attempt_id
) VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
) ON CONFLICT (memory_id) DO UPDATE SET
    tier = excluded.tier, content = excluded.content,
    weight = excluded.weight, org_id = excluded.org_id,
    team_id = excluded.team_id, agent_id = excluded.agent_id,
    user_id = excluded.user_id, scope = excluded.scope,
    project_id = excluded.project_id, source = excluded.source,
    context = excluded.context,
    reinforcement_count = excluded.reinforcement_count,
    contradiction_count = excluded.contradiction_count,
    created_at = excluded.created_at,
    last_accessed_at = excluded.last_accessed_at,
    deleted = excluded.deleted, decay_rate = excluded.decay_rate,
    shared = excluded.shared,
    flagged_for_review = excluded.flagged_for_review,
    run_id = excluded.run_id, node_run_id = excluded.node_run_id,
    attempt_id = excluded.attempt_id
"""


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
            # Nullable, matching the PostgreSQL column and migration 026's
            # shape for the other record kinds: an empty-string default would
            # make every pre-#64 row claim a Run with an empty id (#64).
            ("run_id", "TEXT"),
            ("node_run_id", "TEXT"),
            ("attempt_id", "TEXT"),
        ):
            if column not in present:
                await self._conn.execute(f"ALTER TABLE episodic_memories ADD COLUMN {column} {ddl}")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_scope_weight "
            "ON episodic_memories (org_id, scope, weight DESC)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_memories_run_id "
            "ON episodic_memories (run_id)"
        )
        await self._conn.commit()

    async def store(self, memory: EpisodicMemory) -> str:
        """Store a memory, naming the execution that produced it.

        Upsert, as in PostgreSQL. The producer is resolved before the write by
        the same rule every provenance-bearing store uses: caller first,
        ambient context second, none stored as NULL (#64).
        """
        provenance = observed_provenance(
            run_id=memory.run_id,
            node_run_id=memory.node_run_id,
            attempt_id=memory.attempt_id,
        )
        memory.run_id = provenance.run_id
        memory.node_run_id = provenance.node_run_id
        memory.attempt_id = provenance.attempt_id
        await self._conn.execute(_UPSERT, to_row(memory, text_timestamps=True))
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

    async def reinforce(self, memory_id: str, delta: float = REINFORCE_DELTA) -> None:
        """Raise a memory's weight, clamped to its tier ceiling.

        `BEGIN IMMEDIATE` before the read. SQLite serializes writers, but a
        deferred transaction takes its write lock at the first *write*, so two
        connections can both read the old count and both write `count + 1` —
        the lost feedback event `PgEpisodicStore.reinforce` locks against
        (Codex, #710). Taking the lock up front makes the second connection
        wait instead of reading a snapshot it is about to invalidate.
        """
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            found = await self._fetch(f"{_SELECT} WHERE memory_id = ?", (memory_id,))
            if found:
                updated = _reinforce(found[0], delta)
                await self._conn.execute(
                    "UPDATE episodic_memories SET weight = ?, reinforcement_count = ?"
                    " WHERE memory_id = ?",
                    (updated.weight, updated.reinforcement_count, memory_id),
                )
        except BaseException:
            await self._conn.rollback()
            raise
        await self._conn.commit()

    async def apply_decay(self, *, now: datetime | None = None) -> DecaySweep:
        """Decay every live memory once, reporting what the sweep touched."""
        moment = now or datetime.now(UTC)
        scanned = decayed = at_floor = 0
        # The whole sweep under one write lock, taken before the read: reading
        # the live set and writing it back afterwards would discard every
        # reinforcement made in between. The PostgreSQL store takes the same
        # lock per row; one lock for the sweep here, because SQLite has no row
        # locks and a single writer is its model anyway (Codex, #710).
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            for memory in await self._fetch(f"{_SELECT} WHERE deleted = 0", ()):
                floor = clamp_weight(memory.tier, float("-inf"))
                swept = _tick_decay(memory, now=moment)
                await self._conn.execute(
                    "UPDATE episodic_memories SET weight = ?, last_accessed_at = ?"
                    " WHERE memory_id = ?",
                    (swept.weight, swept.last_accessed_at.isoformat(), memory.memory_id),
                )
                scanned += 1
                decayed += swept.weight != memory.weight
                at_floor += swept.weight <= floor
        except BaseException:
            await self._conn.rollback()
            raise
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

    async def produced_by(self, run_id: str, *, org_id: str = "") -> list[EpisodicMemory]:
        """The memories this Run stored, newest first.

        Same rule as the PostgreSQL original and `SqliteLearningStore`
        (#709): a blank `run_id` returns nothing, and `org_id` is a predicate
        in the WHERE rather than a post-filter (#64).
        """
        if not run_id:
            return []
        return await self._fetch(
            f"{_SELECT} WHERE run_id = ? AND org_id = ? AND deleted = 0"
            " ORDER BY created_at DESC, memory_id",
            (run_id, org_id),
        )
