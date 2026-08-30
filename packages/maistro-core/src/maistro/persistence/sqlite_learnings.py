"""SQLite-backed learning store (homelab/single-instance deployments)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from maistro.observability.correlation import observed_provenance
from maistro.types.memory import Learning, MemoryScope

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT 'general',
    trigger_keys TEXT NOT NULL DEFAULT '[]',
    learning TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    user_id TEXT,
    org_id TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'agent',
    hit_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    rca_category TEXT,
    rca_prevention TEXT NOT NULL DEFAULT '',
    success_after_use INTEGER NOT NULL DEFAULT 0,
    failure_after_use INTEGER NOT NULL DEFAULT 0,
    run_id TEXT,
    node_run_id TEXT,
    attempt_id TEXT
)
"""

#: The producer columns, nullable for the same reason migration 025 makes them
#: nullable in PostgreSQL: a row written with no execution in scope names none,
#: and `''` would name a Run whose id is empty (#709).
_PROVENANCE_COLUMNS = ("run_id", "node_run_id", "attempt_id")


class SqliteLearningStore:
    """SQLite-backed learning store implementing the same protocol as PgLearningStore."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        """Create the learnings table, and upgrade one created before its columns.

        `org_id` was in the `Learning` dataclass and in every store method's
        signature long before it was a column, so a database created by an
        earlier version has rows the scope filter cannot see. SQLite has no
        `ADD COLUMN IF NOT EXISTS`, so the column list is inspected first;
        `ALTER TABLE ... ADD COLUMN` with a constant default is a metadata-only
        operation, so this is cheap even on a large table.
        """
        await self._conn.execute(_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(learnings)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "org_id" not in columns:
            await self._conn.execute(
                "ALTER TABLE learnings ADD COLUMN org_id TEXT NOT NULL DEFAULT ''"
            )
        # The same in-place upgrade for the producer columns. A file created
        # before #709 holds real learnings; recreating the table would be the
        # only alternative, and it would lose them (#709).
        for column in _PROVENANCE_COLUMNS:
            if column not in columns:
                await self._conn.execute(f"ALTER TABLE learnings ADD COLUMN {column} TEXT")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_learnings_run_id ON learnings (run_id)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_learnings_scope ON learnings (org_id, agent_id, status)"
        )
        await self._conn.commit()

    async def store(self, learning: Learning) -> int:
        """Store a learning, naming the execution that produced it.

        Resolved before the dedup probe for the same reason as the PostgreSQL
        original: the deduplicating branch returns early (#709).
        """
        provenance = observed_provenance(
            run_id=learning.run_id,
            node_run_id=learning.node_run_id,
            attempt_id=learning.attempt_id,
        )
        # Scope the dedup probe too. Without `org_id` here, storing a learning
        # for org A could match org B's row, bump B's hit_count and return B's
        # id to A — a cross-scope write and an id leak, not merely a missed
        # insert.
        cursor = await self._conn.execute(
            "SELECT id, trigger_keys FROM learnings "
            "WHERE tool_name = ? AND org_id = ? AND status = 'active'",
            (learning.tool_name, learning.org_id or ""),
        )
        existing = await cursor.fetchall()
        new_keys = set(learning.trigger_keys)
        for row in existing:
            existing_keys = set(json.loads(row[1]))
            if new_keys and existing_keys:
                overlap = len(new_keys & existing_keys) / len(new_keys)
                if overlap >= 0.5:
                    await self._conn.execute(
                        "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = ?",
                        (row[0],),
                    )
                    await self._conn.commit()
                    return int(row[0])

        insert_cursor = await self._conn.execute(
            """INSERT INTO learnings
               (category, trigger_keys, learning, tool_name,
                agent_id, user_id, org_id, scope, status,
                rca_category, rca_prevention,
                success_after_use, failure_after_use,
                run_id, node_run_id, attempt_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                learning.category,
                json.dumps(list(learning.trigger_keys)),
                learning.learning,
                learning.tool_name,
                learning.agent_id or "",
                learning.user_id,
                learning.org_id or "",
                learning.scope,
                learning.status,
                learning.rca_category,
                learning.rca_prevention,
                learning.success_after_use,
                learning.failure_after_use,
                provenance.run_id or None,
                provenance.node_run_id or None,
                provenance.attempt_id or None,
            ),
        )
        await self._conn.commit()
        return insert_cursor.lastrowid or 0

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Find relevant learnings by keyword match, within `org_id`'s scope.

        `org_id` was accepted and ignored: the query was
        `SELECT * FROM learnings WHERE status = 'active'` with no scope
        predicate at all, and the results are interpolated into the agent's
        *system* prompt. Filtering matters here more than in a normal read path
        because a learning is an instruction, not a datum.

        Org matching is exact: `org_id` matches only rows carrying that same
        `org_id`, and an empty `org_id` matches only rows that have none. There
        is deliberately no global bucket. An earlier form of this predicate
        also admitted `org_id = ''` rows to every caller, mirroring the
        `agent_id = ''` convention on the line below, but the two are not
        analogous — `agent_id = ''` widens within one org, while `org_id = ''`
        crosses the tenancy boundary that SPEC-216 names a non-goal ("cross-org
        learning sharing of any kind"). Any write path that failed to set
        `org_id` silently published into that bucket, and a learning is an
        instruction interpolated into the system prompt, not a datum.

        This matches `InMemoryLearningStore`, the reference implementation the
        spec describes; the SQL stores had drifted from it.
        """
        query = "SELECT * FROM learnings WHERE status = 'active'"
        params: list[Any] = []
        query += " AND org_id = ?"
        params.append(org_id)
        if agent_id:
            query += " AND (agent_id = ? OR agent_id = '')"
            params.append(agent_id)

        cursor = await self._conn.execute(query, params)
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()

        text_lower = user_text.lower()
        scored: list[tuple[float, Learning]] = []
        for raw in rows:
            row = dict(zip(columns, raw, strict=True))
            keys: list[str] = json.loads(row["trigger_keys"])
            score = sum(1 for k in keys if k.lower() in text_lower)
            if score > 0:
                scored.append((float(score), _row_to_learning(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [lr for _, lr in scored[:max_results]]

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for given IDs."""
        if not learning_ids:
            return
        placeholders = ",".join("?" for _ in learning_ids)
        await self._conn.execute(
            f"UPDATE learnings SET hit_count = hit_count + 1 WHERE id IN ({placeholders})",  # nosec B608
            learning_ids,
        )
        await self._conn.commit()

    async def produced_by(self, run_id: str, *, org_id: str = "") -> list[Learning]:
        """Return the learnings this Run produced, newest first.

        Same rule as the PostgreSQL original, including that a blank `run_id`
        returns nothing rather than every unattributed row (#709).
        """
        if not run_id:
            return []
        cursor = await self._conn.execute(
            "SELECT * FROM learnings WHERE run_id = ? AND org_id = ? ORDER BY id DESC",
            (run_id, org_id),
        )
        # `cursor.description`, not a row factory: `aiosqlite` is a
        # `TYPE_CHECKING`-only import here, and setting `row_factory` on the
        # shared connection would change what every other method on it returns.
        names = [column[0] for column in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_learning(dict(zip(names, row, strict=True))) for row in rows]

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        """Increment success/failure counters per id."""
        if not learning_ids:
            return
        placeholders = ",".join("?" for _ in learning_ids)
        column = "success_after_use" if success else "failure_after_use"
        # Scoped like find_relevant: a caller may only move counters on rows it
        # could have been served. Unscoped, an id from another org would be
        # accepted and written, so a guessed id was a cross-scope write.
        await self._conn.execute(
            f"UPDATE learnings SET {column} = {column} + 1 "  # nosec B608
            f"WHERE id IN ({placeholders}) AND org_id = ?",
            [*learning_ids, org_id],
        )
        await self._conn.commit()

    async def check_auto_promotions(
        self,
        threshold: int = 5,
        org_id: str = "",
    ) -> list[Learning]:
        """Promote learnings with hit_count >= threshold."""
        cursor = await self._conn.execute(
            "SELECT id FROM learnings WHERE status = 'active' AND hit_count >= ? AND org_id = ?",
            (threshold, org_id),
        )
        ids = [r[0] for r in await cursor.fetchall()]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        await self._conn.execute(
            f"UPDATE learnings SET status = 'promoted' WHERE id IN ({placeholders})",  # nosec B608
            ids,
        )
        await self._conn.commit()

        select_cursor = await self._conn.execute(
            f"SELECT * FROM learnings WHERE id IN ({placeholders})",  # nosec B608
            ids,
        )
        columns = [d[0] for d in select_cursor.description]
        rows = await select_cursor.fetchall()
        return [_row_to_learning(dict(zip(columns, r, strict=True))) for r in rows]

    async def get_promoted(
        self,
        task_type: str | None = None,
        org_id: str = "",
    ) -> list[Learning]:
        """Get promoted learnings."""
        query = "SELECT * FROM learnings WHERE status = 'promoted' AND org_id = ?"
        params: list[Any] = [org_id]
        if task_type:
            query += " AND category = ?"
            params.append(task_type)
        cursor = await self._conn.execute(query, params)
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_learning(dict(zip(columns, r, strict=True))) for r in rows]

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        """List all learnings (admin endpoint)."""
        cursor = await self._conn.execute(
            "SELECT * FROM learnings WHERE org_id = ? ORDER BY id DESC LIMIT ?",
            (org_id, limit),
        )
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_learning(dict(zip(columns, r, strict=True))) for r in rows]


def _row_to_learning(row: dict[str, Any]) -> Learning:
    return Learning(
        id=row["id"],
        category=row.get("category") or "",
        trigger_keys=json.loads(row.get("trigger_keys") or "[]"),
        learning=row["learning"],
        tool_name=row.get("tool_name") or "",
        agent_id=row.get("agent_id") or None,
        user_id=row.get("user_id"),
        org_id=row.get("org_id") or "",
        scope=MemoryScope(row.get("scope") or "agent"),
        hit_count=row.get("hit_count", 0),
        status=row.get("status") or "active",
        rca_category=row.get("rca_category"),
        rca_prevention=row.get("rca_prevention") or "",
        run_id=row.get("run_id") or "",
        node_run_id=row.get("node_run_id") or "",
        attempt_id=row.get("attempt_id") or "",
        success_after_use=row.get("success_after_use", 0),
        failure_after_use=row.get("failure_after_use", 0),
    )
