"""PostgreSQL learning store."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from maistro.types.memory import Learning

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger("maistro.persistence.learnings")


class PgLearningStore:
    """PostgreSQL-backed learning store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        """Add the `org_id` column and its index if they are missing.

        Deliberately ALTER-only, with no CREATE TABLE. Unlike the SQLite store,
        nothing in this repository defines the Postgres `learnings` table —
        `grep -rn "CREATE TABLE .*learnings"` finds only `sqlite_learnings.py`.
        The table is therefore owned by whatever provisions the deployment's
        database, and inventing a full definition here would risk diverging
        from it. Adding one nullable-with-default column is a safe, idempotent
        upgrade that does not claim that ownership.

        This exists because the queries in this class now name `org_id`; a
        deployment that never runs it would get "column does not exist" rather
        than the unfiltered results it used to get. Failing loudly on a missing
        scope column is the correct direction for a filter whose absence is a
        cross-scope read.
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
        """Store a learning. Dedup by tool_name + trigger_key overlap."""
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
                """INSERT INTO learnings
                   (category, trigger_keys, learning, tool_name, source_query,
                    agent_id, user_id, org_id, team_id, scope, hit_count, status,
                    rca_category, rca_prevention,
                    success_after_use, failure_after_use)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                           $13, $14, $15, $16)
                   RETURNING id""",
                learning.category,
                _dump_keys(learning.trigger_keys),
                learning.learning,
                learning.tool_name,
                # `source_query` and `team_id` are NOT NULL in migration 001
                # with no DDL default -- SQLAlchemy's `default=` is applied by
                # the ORM, and this is a raw INSERT. Omitting them was a
                # NotNullViolation, and omitting `team_id` in particular
                # dropped the row's team scope on a column the store then
                # filters on.
                learning.source_query,
                learning.agent_id or "",
                learning.user_id,
                learning.org_id or "",
                learning.team_id,
                learning.scope,
                learning.hit_count,
                learning.status,
                learning.rca_category,
                learning.rca_prevention,
                learning.success_after_use,
                learning.failure_after_use,
            )
            return int(row["id"]) if row else 0

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
            keys: list[str] = row["trigger_keys"] or []
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
    )
