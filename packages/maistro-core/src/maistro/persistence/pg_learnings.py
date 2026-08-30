"""PostgreSQL learning store."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from maistro.memory.vectors import EMBEDDING_DIMENSIONS, to_pgvector_literal
from maistro.observability.correlation import observed_provenance
from maistro.types.memory import Learning

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger("maistro.persistence.learnings")

#: pgvector's filtered-recall mode for HNSW. Named so the reason for
#: `relaxed_order` over `strict_order` sits with the value rather than only
#: in the query that uses it.
_ITERATIVE_SCAN = "relaxed_order"


def similarity_query(*, scoped_to_agent: bool) -> str:
    """The SQL `find_similar` runs, built in one place.

    A module function rather than an inline string so a test can `EXPLAIN` the
    real query. The property #188 is about -- that PostgreSQL applies the scope
    filter, rather than Python applying it after an unscoped fetch -- is only
    visible in the plan, and a plan check against a hand-copied query proves
    nothing about the query that actually runs.
    """
    agent_clause = " AND (agent_id = $3 OR agent_id = '')" if scoped_to_agent else ""
    limit_placeholder = 4 if scoped_to_agent else 3
    return (
        "SELECT * FROM learnings"
        " WHERE status = 'active'"
        " AND org_id = $2"
        " AND embedding IS NOT NULL"
        f"{agent_clause}"
        f" ORDER BY embedding <=> $1::vector LIMIT ${limit_placeholder}"
    )


class PgLearningStore:
    """PostgreSQL-backed learning store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        """Add the `org_id` column and its index if they are missing.

        ALTER-only, with no CREATE TABLE, because the table has an owner:
        `alembic/versions/` defines `learnings` and every column this class
        reads. (An earlier version of this docstring said nothing in the
        repository defined the table. That was already wrong when written —
        migration 001 creates it — and acting on it is part of how the schema
        drifted from the stores until #122 ran the two against each other.)

        What remains here is a belt-and-braces upgrade for a database migrated
        before `org_id` existed: idempotent, cheap, and safe to run at startup.
        Failing loudly on a missing scope column is the right direction for a
        filter whose absence is a cross-scope read — but the migration is what
        should be relied on, not this.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT ''"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learnings_scope "
                "ON learnings (org_id, agent_id, status)"
            )

    async def store(self, learning: Learning) -> int:
        """Store a learning, naming the execution that produced it.

        Resolved before the dedup read, not after: the deduplicating branch
        returns early, and a provenance read that only happens on the insert
        path would be a second place for the rule to live (#709).
        """
        provenance = observed_provenance(
            run_id=learning.run_id,
            node_run_id=learning.node_run_id,
            attempt_id=learning.attempt_id,
        )
        async with self._pool.acquire() as conn:
            existing = await conn.fetch(
                """SELECT id, trigger_keys FROM learnings
                   WHERE tool_name = $1 AND org_id = $2 AND status = 'active'""",
                learning.tool_name,
                learning.org_id or "",
            )
            for row in existing:
                existing_keys = set(_load_keys(row["trigger_keys"]))
                new_keys = set(learning.trigger_keys)
                if new_keys and existing_keys:
                    overlap = len(new_keys & existing_keys) / len(new_keys)
                    if overlap >= 0.5:
                        await conn.execute(
                            "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = $1",
                            row["id"],
                        )
                        return int(row["id"])

            row = await conn.fetchrow(
                # source_query, team_id and hit_count are written, not
                # omitted: all three are columns the read paths select, and a
                # column the writer skips is a column that always reads back as
                # its default. `hit_count` is usually 0 on a new learning, but
                # a caller that supplies one — a re-import, a merge — must get
                # it back, and `find_relevant` orders by it.
                """INSERT INTO learnings
                   (category, trigger_keys, learning, tool_name, source_query,
                    agent_id, user_id, org_id, team_id, scope, hit_count, status,
                    rca_category, rca_prevention,
                    success_after_use, failure_after_use,
                    run_id, node_run_id, attempt_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                           $13, $14, $15, $16, $17, $18, $19)
                   RETURNING id""",
                learning.category,
                _dump_keys(learning.trigger_keys),
                learning.learning,
                learning.tool_name,
                learning.source_query,
                learning.agent_id or "",
                learning.user_id,
                learning.org_id or "",
                learning.team_id or "",
                learning.scope,
                learning.hit_count,
                learning.status,
                learning.rca_category,
                learning.rca_prevention,
                learning.success_after_use,
                learning.failure_after_use,
                # `or None`, three times: an empty string in a provenance column
                # reads as "produced by a Run whose id is empty", which is a
                # claim. NULL reads as "no execution was in scope", which is
                # what happened (#709).
                provenance.run_id or None,
                provenance.node_run_id or None,
                provenance.attempt_id or None,
            )
            return int(row["id"]) if row else 0

    async def text_of(self, learning_id: int) -> str:
        """The learning text as it is actually stored.

        `store` deduplicates, so the id it returns may belong to a row whose
        text differs from the one just submitted. A caller that embeds the
        submitted text would stamp the surviving row with a vector describing
        content it does not hold. Reading the row back is the only way to know
        what the vector should describe.
        """
        async with self._pool.acquire() as conn:
            text = await conn.fetchval("SELECT learning FROM learnings WHERE id = $1", learning_id)
        return str(text) if text else ""

    async def set_embedding(self, learning_id: int, vector: list[float]) -> None:
        """Attach an embedding to a stored learning.

        The producer half of #188. `HybridLearningStore` kept vectors in a
        process-local `dict[int, list[float]]`, so every restart threw away
        every embedding and re-embedded on next read -- which is why the column
        is the point and not an optimisation.

        Refuses a vector the schema cannot store rather than letting PostgreSQL
        raise on the cast: the error here names the learning and both widths.
        """
        if len(vector) != EMBEDDING_DIMENSIONS:
            msg = (
                f"learning {learning_id} was given a {len(vector)}-dimension embedding, "
                f"but the column is vector({EMBEDDING_DIMENSIONS}) (ADR-082326-8194)"
            )
            raise ValueError(msg)

        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE learnings SET embedding = $1::vector WHERE id = $2",
                to_pgvector_literal(vector),
                learning_id,
            )

    async def find_similar(
        self,
        query_embedding: list[float],
        *,
        org_id: str = "",
        agent_id: str | None = None,
        max_results: int = 10,
    ) -> list[Learning]:
        """Scope-filtered, similarity-ranked learnings, in one query.

        This is the whole point of putting the vector on the row (#188). The
        scope predicate is in the `WHERE` clause, so PostgreSQL applies it
        *before* returning rows -- not afterwards in Python, which is both
        slower and a scope-leak surface, because a filter that runs after the
        fetch is one a caller can forget to run.

        Ordering is by `<=>`, pgvector's cosine distance, matching
        `memory/learnings/embeddings.py::cosine_similarity` and the
        `vector_cosine_ops` index migration 007 builds. An L2-ordered query
        against a cosine index still returns rows; it just scans instead of
        using the index, which is the kind of regression only a plan check
        catches.

        `embedding IS NOT NULL` is not an optimisation: a row with no vector has
        no distance to the query, and pgvector sorts NULLs last rather than
        excluding them, so without it an unembedded corpus returns `max_results`
        arbitrary rows that look ranked.
        """
        if len(query_embedding) != EMBEDDING_DIMENSIONS:
            msg = (
                f"query embedding is {len(query_embedding)}-dimensional, but the column "
                f"is vector({EMBEDDING_DIMENSIONS}) (ADR-082326-8194)"
            )
            raise ValueError(msg)

        params: list[Any] = [to_pgvector_literal(query_embedding), org_id]
        if agent_id:
            params.append(agent_id)
        query = similarity_query(scoped_to_agent=bool(agent_id))
        params.append(max_results)

        # HNSW searches approximately and *then* applies the scope predicate, so
        # on a large multi-org table the candidate set can be dominated by other
        # scopes and this query returns too few rows -- or none -- while
        # matching in-scope vectors exist. A small corpus never shows it,
        # because the planner picks a sequential scan and the filter is exact.
        #
        # `iterative_scan` (pgvector 0.8+) makes the index keep fetching until
        # the filtered result set is full. `relaxed_order` rather than
        # `strict_order`: strict re-sorts every batch to guarantee global
        # distance order and costs more for a ranking that is already
        # approximate. `SET LOCAL` inside the transaction, so nothing outside it
        # inherits the setting.
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(f"SET LOCAL hnsw.iterative_scan = {_ITERATIVE_SCAN}")
            rows = await conn.fetch(query, *params)

        return [_row_to_learning(row) for row in rows]

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Find relevant learnings by keyword match, within `org_id`'s scope.

        Same defect and same rule as `SqliteLearningStore.find_relevant`:
        `org_id` was accepted and never used, while the results are
        interpolated into the agent's system prompt. Org matching is exact —
        an empty `org_id` matches only rows that have none, and there is no
        global bucket that every org can read. See that method's docstring for
        why `org_id = ''` is not analogous to the `agent_id = ''` widening
        still used below.
        """
        async with self._pool.acquire() as conn:
            query = """
                SELECT * FROM learnings
                WHERE status = 'active'
                  AND org_id = $1
            """
            params: list[Any] = [org_id]
            if agent_id:
                query += " AND (agent_id = $2 OR agent_id = '')"
                params.append(agent_id)

            rows = await conn.fetch(query, *params)

        text_lower = user_text.lower()
        scored: list[tuple[float, Learning]] = []
        for row in rows:
            # `_load_keys`, not the raw column. asyncpg hands JSONB back as
            # text, so iterating it scored one *character* at a time: a
            # learning keyed ["timeout"] matched the query "cat" on the shared
            # letter `t`, and since almost every key shares a letter with
            # almost every query, nearly every learning scored above zero and
            # was injected into the agent's system prompt. The annotation said
            # list[str] and the value was a str, which is why it type-checked.
            keys = _load_keys(row["trigger_keys"])
            score = sum(1 for k in keys if k.lower() in text_lower)
            if score > 0:
                scored.append((float(score), _row_to_learning(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [lr for _, lr in scored[:max_results]]

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for given IDs."""
        if not learning_ids:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = ANY($1::int[])",
                learning_ids,
            )

    async def produced_by(self, run_id: str, *, org_id: str = "") -> list[Learning]:
        """Return the learnings this Run produced, newest first.

        An empty `run_id` returns nothing rather than every row whose producer
        is NULL. "Which learnings did no execution produce" is a legitimate
        question, but it is a different one, and answering it from the same
        call means a caller with an unresolved id silently gets the wrong set.
        """
        if not run_id:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM learnings
                   WHERE run_id = $1 AND org_id = $2
                   ORDER BY id DESC""",
                run_id,
                org_id,
            )
        return [_row_to_learning(row) for row in rows]

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        """Increment success/failure counters per id."""
        if not learning_ids:
            return
        async with self._pool.acquire() as conn:
            # Scoped like find_relevant: only rows this caller could have been
            # served may have their counters moved. Ids are integers, so an
            # unscoped update accepted a guessed id from any scope.
            column = "success_after_use" if success else "failure_after_use"
            await conn.execute(
                f"UPDATE learnings SET {column} = {column} + 1 "  # nosec B608
                "WHERE id = ANY($1::int[]) AND org_id = $2",
                learning_ids,
                org_id,
            )

    async def check_auto_promotions(
        self,
        threshold: int = 5,
        org_id: str = "",
    ) -> list[Learning]:
        """Promote learnings with hit_count >= threshold."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """UPDATE learnings SET status = 'promoted'
                   WHERE status = 'active' AND hit_count >= $1
                     AND org_id = $2
                   RETURNING *""",
                threshold,
                org_id,
            )
            return [_row_to_learning(r) for r in rows]

    async def get_promoted(
        self,
        task_type: str | None = None,
        org_id: str = "",
    ) -> list[Learning]:
        """Get promoted learnings."""
        async with self._pool.acquire() as conn:
            query = "SELECT * FROM learnings WHERE status = 'promoted' AND org_id = $1"
            params: list[Any] = [org_id]
            if task_type:
                query += " AND category = $2"
                params.append(task_type)
            rows = await conn.fetch(query, *params)
            return [_row_to_learning(r) for r in rows]

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        """List all learnings (admin endpoint)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM learnings WHERE org_id = $1 ORDER BY id DESC LIMIT $2",
                org_id,
                limit,
            )
            return [_row_to_learning(r) for r in rows]


def _dump_keys(keys: list[str]) -> str:
    """Encode `trigger_keys` for the JSONB column migration 001 declares.

    asyncpg's default JSONB codec is `str` in both directions -- it does not
    serialise Python objects. Passing a `list` raised, and reading a row back
    with `list(row["trigger_keys"])` split the raw JSON *text* into single
    characters, so a stored `["timeout", "retry"]` came back as
    `['[', '"', 't', 'i', ...]`. The write half failed loudly and the read half
    corrupted silently.

    The conversion lives here rather than in a pool-level `set_type_codec`
    because a store whose correctness depends on how someone else constructed
    the pool is the same class of hidden coupling that produced #122. This one
    is right however it is wired.
    """
    return json.dumps(list(keys))


def _load_keys(raw: object) -> list[str]:
    """Decode `trigger_keys`, tolerating a pool that *does* register a codec.

    Returns `[]` for NULL or for text that is not a JSON array of strings,
    rather than raising: a malformed row should cost that one learning, not
    every query that happens to touch it.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(k) for k in raw]
    if isinstance(raw, str | bytes | bytearray):
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError):
            return []
        if isinstance(decoded, list):
            return [str(k) for k in decoded]
    return []


def _row_to_learning(row: asyncpg.Record) -> Learning:
    return Learning(
        id=row["id"],
        category=row.get("category", ""),
        trigger_keys=_load_keys(row.get("trigger_keys")),
        learning=row["learning"],
        tool_name=row.get("tool_name", ""),
        # `source_query` and `team_id` are stored and were never read back, so
        # every `Learning` this store returned carried the dataclass default
        # rather than the row's value -- a round-trip that loses the team scope
        # it filters on, and the query the learning was derived from.
        source_query=row.get("source_query", ""),
        agent_id=row.get("agent_id") or None,
        user_id=row.get("user_id"),
        org_id=row.get("org_id") or "",
        team_id=row.get("team_id") or "",
        scope=row.get("scope", "agent"),
        hit_count=row.get("hit_count", 0),
        status=row.get("status", "active"),
        rca_category=row.get("rca_category"),
        rca_prevention=row.get("rca_prevention", ""),
        success_after_use=row.get("success_after_use", 0),
        failure_after_use=row.get("failure_after_use", 0),
        # `or ""` because the columns are nullable and the dataclass fields are
        # not: a row with no producer comes back as a Learning naming none,
        # which is the same fact in the shape the caller expects (#709).
        run_id=row.get("run_id") or "",
        node_run_id=row.get("node_run_id") or "",
        attempt_id=row.get("attempt_id") or "",
    )
