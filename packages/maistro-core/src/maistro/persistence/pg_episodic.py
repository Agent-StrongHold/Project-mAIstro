"""PostgreSQL episodic memory store (ADR-083026-a322).

`episodic_memories` existed from migration 001 and no Python outside `alembic/`
named it: the only `EpisodicStore` was a list on the heap, wired even under a
`postgresql://` URL. This is the reader and the writer.

Two properties are deliberate and each has a test.

**The scope filter runs in the database.** The predicate comes from
`maistro.memory.scopes.scope_predicate`, compiled from the same filter list
`matches_scope` decides on, so a durable read applies the cross-org rules rather
than fetching every row and letting Python sort it out (#188's property, for the
reason #622 gives: one rule, not a second spelling).

**The decay formula stays in Python.** `apply_decay` reads the live rows,
applies `tick_decay` -- the function the in-memory store applies -- and writes
each back. An `UPDATE` restating the arithmetic would drift from a formula that
reads each row's own `decay_rate` and `last_accessed_at`.
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
    import asyncpg

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM episodic_memories"


def _placeholders(start: int) -> Any:
    """`$n` markers from `start` upward, for `scope_predicate`."""
    return (f"${index}" for index in itertools.count(start))


class PgEpisodicStore:
    """PostgreSQL-backed episodic store: `EpisodicStore` + `DecayableEpisodicStore`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        """Belt-and-braces for a database migrated before 025.

        ALTER-only, no CREATE TABLE: `alembic/versions/` owns this table, and
        `PgLearningStore.ensure_schema` records why a store that creates its own
        is how the schema drifts from the migrations. The four columns here are
        the ones the record has always carried, so a database one revision
        behind loses four fields silently rather than failing -- which is worse
        than a cheap idempotent ALTER at startup.
        """
        async with self._pool.acquire() as conn:
            for column, ddl in (
                ("project_id", "TEXT NOT NULL DEFAULT ''"),
                ("decay_rate", "DOUBLE PRECISION NOT NULL DEFAULT 0.01"),
                ("shared", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("flagged_for_review", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ):
                await conn.execute(
                    f"ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS {column} {ddl}"
                )

    async def store(self, memory: EpisodicMemory) -> str:
        """Store a memory. Returns its `memory_id`.

        An upsert, because `memory_id` is `UNIQUE` on the table and a second
        `store` of the same id would otherwise raise. `InMemoryEpisodicStore`
        appends and would hold two; one row per id is the durable answer, and
        the id is the record's identity in every other method here.
        """
        assignments = ", ".join(f"{name} = EXCLUDED.{name}" for name in COLUMNS[1:])
        markers = ", ".join(f"${index}" for index in range(1, len(COLUMNS) + 1))
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO episodic_memories ({', '.join(COLUMNS)}) VALUES ({markers})"
                f" ON CONFLICT (memory_id) DO UPDATE SET {assignments}",
                *to_row(memory, text_encoded=False),
            )
        return memory.memory_id

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
            _placeholders(1),
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"{_SELECT} WHERE deleted = FALSE AND ({predicate})"
                f" ORDER BY weight DESC, memory_id LIMIT ${len(params) + 1}",
                *params,
                RETRIEVAL_CANDIDATE_CAP,
            )
        # The same `rank` the in-memory store calls. #622 collapsed four
        # spellings of ADR-080 part D into this function; a SQL restatement
        # would be the fifth.
        return rank(query, [from_row(row) for row in rows], k=limit)

    async def reinforce(self, memory_id: str, delta: float = 0.05) -> None:
        """Raise a memory's weight, clamped to its tier ceiling."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"{_SELECT} WHERE memory_id = $1", memory_id)
            if row is None:
                return
            updated = _reinforce(from_row(row), delta)
            await conn.execute(
                "UPDATE episodic_memories SET weight = $1, reinforcement_count = $2"
                " WHERE memory_id = $3",
                updated.weight,
                updated.reinforcement_count,
                memory_id,
            )

    async def apply_decay(self, *, now: datetime | None = None) -> DecaySweep:
        """Decay every live memory once, reporting what the sweep touched."""
        moment = now or datetime.now(UTC)
        scanned = decayed = at_floor = 0
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(f"{_SELECT} WHERE deleted = FALSE")
            for row in rows:
                memory = from_row(row)
                floor = clamp_weight(memory.tier, float("-inf"))
                swept = _tick_decay(memory, now=moment)
                await conn.execute(
                    "UPDATE episodic_memories SET weight = $1, last_accessed_at = $2"
                    " WHERE memory_id = $3",
                    swept.weight,
                    swept.last_accessed_at,
                    memory.memory_id,
                )
                scanned += 1
                decayed += swept.weight != memory.weight
                at_floor += swept.weight <= floor
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
        sql, params = _scoped_list_query(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
            project_id=project_id,
            min_weight=min_weight,
            limit=limit,
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [from_row(row) for row in rows]


def _scoped_list_query(
    *,
    agent_id: str | None,
    user_id: str | None,
    team_id: str | None,
    org_id: str | None,
    project_id: str | None,
    min_weight: float,
    limit: int,
) -> tuple[str, list[Any]]:
    """The SQL `list_by_scope` runs, built in one place.

    A module function so a test can `EXPLAIN` the query that actually runs
    rather than a hand-copied one: what AC-4 is about -- that the scope filter
    is the server's work -- is only visible in the plan.
    """
    markers = _placeholders(1)
    params: list[Any] = []
    clauses = ["deleted = FALSE"]
    # No agent/user/team/org filter: `project_id` alone selects, independent of
    # the scope hierarchy. `InMemoryEpisodicStore` does the same, for project
    # changelog recall.
    if agent_id or user_id or team_id or org_id:
        predicate, scope_params = scope_predicate(
            build_scope_filter(agent_id=agent_id, user_id=user_id, team_id=team_id, org_id=org_id),
            markers,
        )
        clauses.append(f"({predicate})")
        params.extend(scope_params)
    params.append(min_weight)
    clauses.append(f"weight >= {next(markers)}")
    if project_id:
        params.append(project_id)
        clauses.append(f"project_id = {next(markers)}")
    params.append(limit)
    return (
        f"{_SELECT} WHERE {' AND '.join(clauses)}"
        f" ORDER BY weight DESC, memory_id LIMIT {next(markers)}",
        params,
    )
