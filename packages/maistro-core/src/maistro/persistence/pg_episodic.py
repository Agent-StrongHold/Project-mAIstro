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
from maistro.observability.correlation import observed_provenance
from maistro.persistence.episodic_rows import (
    COLUMNS,
    RETRIEVAL_CANDIDATE_CAP,
    from_row,
    to_row,
)
from maistro.types.memory import REINFORCE_DELTA, DecaySweep, EpisodicMemory

if TYPE_CHECKING:
    import asyncpg

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM episodic_memories"

#: The upsert, written out rather than assembled from `COLUMNS`.
#:
#: `$12::text::jsonb` is `context`: bound as text and cast by the server, so
#: the write does not depend on the connection carrying the JSON codecs
#: `get_pool` registers -- a caller-supplied pool need not (Codex, #710).
#: See `episodic_rows.to_row` for why the text is not passed uncast.
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
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::text::jsonb, $13,
    $14, $15, $16, $17, $18, $19, $20, $21, $22, $23
) ON CONFLICT (memory_id) DO UPDATE SET
    tier = EXCLUDED.tier, content = EXCLUDED.content,
    weight = EXCLUDED.weight, org_id = EXCLUDED.org_id,
    team_id = EXCLUDED.team_id, agent_id = EXCLUDED.agent_id,
    user_id = EXCLUDED.user_id, scope = EXCLUDED.scope,
    project_id = EXCLUDED.project_id, source = EXCLUDED.source,
    context = EXCLUDED.context,
    reinforcement_count = EXCLUDED.reinforcement_count,
    contradiction_count = EXCLUDED.contradiction_count,
    created_at = EXCLUDED.created_at,
    last_accessed_at = EXCLUDED.last_accessed_at,
    deleted = EXCLUDED.deleted, decay_rate = EXCLUDED.decay_rate,
    shared = EXCLUDED.shared,
    flagged_for_review = EXCLUDED.flagged_for_review,
    run_id = EXCLUDED.run_id, node_run_id = EXCLUDED.node_run_id,
    attempt_id = EXCLUDED.attempt_id
"""


def _placeholders(start: int) -> Any:
    """`$n` markers from `start` upward, for `scope_predicate`."""
    return (f"${index}" for index in itertools.count(start))


class PgEpisodicStore:
    """PostgreSQL-backed episodic store: `EpisodicStore` + `DecayableEpisodicStore`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        """Belt-and-braces for a database migrated before the columns.

        ALTER-only, no CREATE TABLE: `alembic/versions/` owns this table, and
        `PgLearningStore.ensure_schema` records why a store that creates its own
        is how the schema drifts from the migrations. The columns here are ones
        the record carries, so a database a revision behind loses them silently
        rather than failing -- which is worse than a cheap idempotent ALTER at
        startup.
        """
        async with self._pool.acquire() as conn:
            for column, ddl in (
                ("project_id", "TEXT NOT NULL DEFAULT ''"),
                ("decay_rate", "DOUBLE PRECISION NOT NULL DEFAULT 0.01"),
                ("shared", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("flagged_for_review", "BOOLEAN NOT NULL DEFAULT FALSE"),
                # Nullable, the shape migration 026 gave learnings, outcomes
                # and design_outputs: `NOT NULL DEFAULT ''` would make every
                # pre-#64 row claim a Run whose id is the empty string (#64).
                ("run_id", "TEXT"),
                ("node_run_id", "TEXT"),
                ("attempt_id", "TEXT"),
            ):
                await conn.execute(
                    f"ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS {column} {ddl}"
                )

    async def store(self, memory: EpisodicMemory) -> str:
        """Store a memory, naming the execution that produced it. Returns its
        `memory_id`.

        An upsert, because `memory_id` is `UNIQUE` on the table and a second
        `store` of the same id would otherwise raise. `InMemoryEpisodicStore`
        appends and would hold two; one row per id is the durable answer, and
        the id is the record's identity in every other method here.

        The producer is resolved before the write: what the caller named beats
        the ambient context, and a write with no execution in scope stores NULL
        rather than an id-shaped empty string (#64).
        """
        provenance = observed_provenance(
            run_id=memory.run_id,
            node_run_id=memory.node_run_id,
            attempt_id=memory.attempt_id,
        )
        memory.run_id = provenance.run_id
        memory.node_run_id = provenance.node_run_id
        memory.attempt_id = provenance.attempt_id
        async with self._pool.acquire() as conn:
            await conn.execute(_UPSERT, *to_row(memory, text_timestamps=False))
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

    async def reinforce(self, memory_id: str, delta: float = REINFORCE_DELTA) -> None:
        """Raise a memory's weight, clamped to its tier ceiling.

        Read and write in one transaction, over a row it has locked. The point
        of a durable store is that replicas share it, so two workers
        reinforcing the same memory is the ordinary case — and an unlocked
        read-modify-write there has both compute `count + 1` from one snapshot
        and one feedback event disappear (Codex, #710). A concurrent decay
        sweep would overwrite the new weight the same way; it takes the same
        lock.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(f"{_SELECT} WHERE memory_id = $1 FOR UPDATE", memory_id)
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
            ids = [
                record["memory_id"]
                for record in await conn.fetch(
                    "SELECT memory_id FROM episodic_memories WHERE deleted = FALSE"
                )
            ]
            for memory_id in ids:
                # One transaction per memory, over a row this one has locked —
                # `reinforce`'s lock from the other side. A sweep that read
                # every row up front and wrote them all back would discard
                # every reinforcement made in between. Per row rather than one
                # long transaction, so a sweep does not hold the whole live set
                # locked (Codex, #710).
                async with conn.transaction():
                    row = await conn.fetchrow(
                        f"{_SELECT} WHERE memory_id = $1 AND deleted = FALSE FOR UPDATE",
                        memory_id,
                    )
                    if row is None:
                        continue
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

    async def produced_by(self, run_id: str, *, org_id: str = "") -> list[EpisodicMemory]:
        """The memories this Run stored, newest first.

        Same rule as `PgLearningStore.produced_by` (#709): a blank `run_id`
        returns nothing rather than every unattributed memory, and `org_id` is
        a predicate in the WHERE clause, so the Run's name cannot widen what a
        caller can read (#64, building on #844's scope rule).
        """
        if not run_id:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"{_SELECT} WHERE run_id = $1 AND org_id = $2 AND deleted = FALSE"
                " ORDER BY created_at DESC, memory_id",
                run_id,
                org_id,
            )
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
