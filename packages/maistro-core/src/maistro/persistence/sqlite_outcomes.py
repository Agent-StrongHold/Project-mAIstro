"""SQLite-backed outcome store (homelab/single-instance deployments)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from maistro.constants import THUMB_LIMIT, THUMB_WINDOW_DAYS
from maistro.types.memory import Outcome

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL DEFAULT '',
    task_type TEXT NOT NULL DEFAULT '',
    model_used TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    tool_calls TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 1,
    error_type TEXT NOT NULL DEFAULT '',
    response_time_ms INTEGER NOT NULL DEFAULT 0,
    team_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    charged_microchips INTEGER NOT NULL DEFAULT 0,
    pricing_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    org_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    dag_id TEXT NOT NULL DEFAULT '',
    dag_run_id TEXT NOT NULL DEFAULT '',
    node_id TEXT NOT NULL DEFAULT '',
    thumb TEXT NOT NULL DEFAULT '',
    thumb_comment TEXT NOT NULL DEFAULT '',
    eval_judge_score REAL
)
"""

# Every column this table gained after its first version. PostgreSQL got them
# in migrations 006 and 010; the SQLite twin got neither, so `record()` had no
# column to write a thumb into and dropped it -- along with the org and project
# the row belonged to. A thumb written to a SQLite deployment was accepted,
# acknowledged with an id, and discarded (#696).
_ADDED_COLUMNS = (
    ("org_id", "TEXT NOT NULL DEFAULT ''"),
    ("project_id", "TEXT NOT NULL DEFAULT ''"),
    ("dag_id", "TEXT NOT NULL DEFAULT ''"),
    ("dag_run_id", "TEXT NOT NULL DEFAULT ''"),
    ("node_id", "TEXT NOT NULL DEFAULT ''"),
    ("thumb", "TEXT NOT NULL DEFAULT ''"),
    ("thumb_comment", "TEXT NOT NULL DEFAULT ''"),
    ("eval_judge_score", "REAL"),
)

_ALLOWED_GROUP_COLUMNS = frozenset({"user_id", "team_id", "model_used", "agent_id", "provider"})


class SqliteOutcomeStore:
    """SQLite-backed outcome store implementing the same protocol as PgOutcomeStore."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        """Create the outcomes table, and upgrade one created before the scope
        and feedback columns.

        SQLite has no `ADD COLUMN IF NOT EXISTS`, so the column list is
        inspected first, the same way `SqliteLearningStore` handles its own
        late `org_id`. `ALTER TABLE ... ADD COLUMN` with a constant default is
        metadata-only, so this stays cheap on a large table.
        """
        await self._conn.execute(_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(outcomes)")
        existing = {row[1] for row in await cursor.fetchall()}
        for column, ddl in _ADDED_COLUMNS:
            if column not in existing:
                await self._conn.execute(f"ALTER TABLE outcomes ADD COLUMN {column} {ddl}")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outcomes_thumb ON outcomes (thumb, created_at)"
        )
        await self._conn.commit()

    async def record(self, outcome: Outcome) -> int:
        """Record an outcome. Returns outcome ID."""
        cursor = await self._conn.execute(
            """INSERT INTO outcomes
               (request_id, task_type, model_used, provider,
                tool_calls, success, error_type, response_time_ms,
                team_id, user_id, agent_id,
                input_tokens, output_tokens, charged_microchips, pricing_version, created_at,
                org_id, project_id, dag_id, dag_run_id, node_id,
                thumb, thumb_comment, eval_judge_score)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                outcome.request_id,
                outcome.task_type,
                outcome.model_used,
                outcome.provider,
                str(outcome.tool_calls),
                1 if outcome.success else 0,
                outcome.error_type,
                outcome.response_time_ms,
                outcome.team_id,
                outcome.user_id,
                outcome.agent_id or "",
                outcome.input_tokens,
                outcome.output_tokens,
                outcome.charged_microchips,
                outcome.pricing_version,
                outcome.created_at.isoformat(),
                outcome.org_id,
                outcome.project_id,
                outcome.dag_id,
                outcome.dag_run_id,
                outcome.node_id,
                outcome.thumb,
                outcome.thumb_comment,
                outcome.eval_judge_score,
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid or 0

    async def get_task_completion_rate(
        self,
        task_type: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> dict[str, Any]:
        """Get completion rate stats."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        query = "SELECT * FROM outcomes WHERE created_at >= ?"
        params: list[Any] = [cutoff]
        if task_type:
            query += " AND task_type = ?"
            params.append(task_type)
        cursor = await self._conn.execute(query, params)
        columns = [d[0] for d in cursor.description]
        raw_rows = await cursor.fetchall()
        rows = [dict(zip(columns, raw, strict=True)) for raw in raw_rows]

        total = len(rows)
        succeeded = sum(1 for r in rows if r["success"])
        by_model: dict[str, dict[str, Any]] = {}
        for r in rows:
            m: str = r["model_used"]
            if m not in by_model:
                by_model[m] = {"total": 0, "succeeded": 0, "rate": 0.0}
            by_model[m]["total"] += 1
            if r["success"]:
                by_model[m]["succeeded"] += 1
        for v in by_model.values():
            v["rate"] = v["succeeded"] / v["total"] if v["total"] else 0.0

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "rate": succeeded / total if total else 0.0,
            "by_model": by_model,
            "days": days,
            "task_type": task_type or "all",
        }

    async def get_usage_breakdown(
        self,
        group_by: str = "user_id",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Aggregate token usage grouped by a dimension."""
        if group_by not in _ALLOWED_GROUP_COLUMNS:
            group_by = "user_id"

        select_cols = f"""SELECT {group_by} AS grp,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(charged_microchips), 0) AS total_microchips,
                       COUNT(*) AS request_count,
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
                       ROUND(AVG(response_time_ms), 1) AS avg_response_ms
                   FROM outcomes"""  # nosec B608

        if days > 0:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            cursor = await self._conn.execute(
                f"""{select_cols}
                   WHERE created_at >= ?
                   GROUP BY {group_by}
                   ORDER BY total_tokens DESC""",  # nosec B608
                (cutoff,),
            )
        else:
            cursor = await self._conn.execute(
                f"""{select_cols}
                   GROUP BY {group_by}
                   ORDER BY total_tokens DESC"""  # nosec B608
            )
        rows = await cursor.fetchall()

        return [
            {
                "group": r[0] or "(unknown)",
                "input_tokens": int(r[1]),
                "output_tokens": int(r[2]),
                "total_tokens": int(r[3]),
                "total_microchips": int(r[4]),
                "request_count": int(r[5]),
                "success_count": int(r[6]),
                "avg_response_ms": float(r[7] or 0),
            }
            for r in rows
        ]

    async def get_daily_timeseries(
        self,
        group_by: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Daily token usage timeseries."""
        has_group = group_by in _ALLOWED_GROUP_COLUMNS
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        if has_group:
            query = f"""
                SELECT DATE(created_at) AS day,
                       {group_by} AS grp,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(charged_microchips), 0) AS total_microchips,
                       COUNT(*) AS request_count
                 FROM outcomes
                 WHERE created_at >= ?
                 GROUP BY day, {group_by}
                 ORDER BY day"""  # nosec B608
        else:
            query = """
                SELECT DATE(created_at) AS day,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(charged_microchips), 0) AS total_microchips,
                       COUNT(*) AS request_count
                FROM outcomes
                WHERE created_at >= ?
                GROUP BY day
                ORDER BY day"""

        cursor = await self._conn.execute(query, (cutoff,))
        rows = await cursor.fetchall()

        if has_group:
            return [
                {
                    "date": str(r[0]),
                    "group": r[1],
                    "input_tokens": int(r[2]),
                    "output_tokens": int(r[3]),
                    "total_tokens": int(r[4]),
                    "total_microchips": int(r[5]),
                    "request_count": int(r[6]),
                }
                for r in rows
            ]
        return [
            {
                "date": str(r[0]),
                "group": None,
                "input_tokens": int(r[1]),
                "output_tokens": int(r[2]),
                "total_tokens": int(r[3]),
                "total_microchips": int(r[4]),
                "request_count": int(r[5]),
            }
            for r in rows
        ]

    async def get_experience_context(
        self,
        task_type: str,
        tool_name: str = "",
        limit: int = 5,
        org_id: str = "",
        project_id: str = "",
    ) -> str:
        """Get recent failure patterns as a prompt section."""
        cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        cursor = await self._conn.execute(
            """SELECT error_type, model_used FROM outcomes
               WHERE task_type = ? AND success = 0
               AND created_at >= ?
               ORDER BY created_at DESC LIMIT ?""",
            (task_type, cutoff, limit),
        )
        rows = await cursor.fetchall()
        if not rows:
            return ""
        lines = ["Recent failures:"]
        for r in rows:
            lines.append(f"- {r[0]}: model={r[1]}")
        return "\n".join(lines)

    async def list_outcomes(
        self,
        task_type: str = "",
        days: int = 7,
        limit: int = 50,
        org_id: str = "",
    ) -> list[Outcome]:
        """List recent outcomes."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        query = "SELECT * FROM outcomes WHERE created_at >= ?"
        params: list[Any] = [cutoff]
        if task_type:
            query += " AND task_type = ?"
            params.append(task_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._conn.execute(query, params)
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()

        return [_row_to_outcome(dict(zip(columns, raw, strict=True))) for raw in rows]

    async def list_thumbs(
        self,
        *,
        dag_id: str = "",
        days: int = THUMB_WINDOW_DAYS,
        limit: int = THUMB_LIMIT,
        org_id: str = "",
    ) -> list[Outcome]:
        """Outcomes carrying a thumb, most recent first.

        `(dag_id = ? OR dag_id = '')` rather than equality, matching
        `_dag_matches`: a thumb with no `dag_id` predates the attribution wire
        and belongs to every DAG. The predicate is pushed into SQL so the limit
        bounds rows that could match, not rows that are then thrown away.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        query = "SELECT * FROM outcomes WHERE created_at >= ? AND thumb <> ''"
        params: list[Any] = [cutoff]
        if dag_id:
            query += " AND (dag_id = ? OR dag_id = '')"
            params.append(dag_id)
        if org_id:
            query += " AND org_id = ?"
            params.append(org_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._conn.execute(query, params)
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_outcome(dict(zip(columns, raw, strict=True))) for raw in rows]


def _row_to_outcome(r: dict[str, Any]) -> Outcome:
    """Map a row to an `Outcome`, including every column the table now has.

    The previous inline mapping stopped at `created_at`, so a round-tripped
    outcome came back with no org, no project, no DAG attribution and no
    thumb -- the same omission `PgOutcomeStore._row_to_outcome` was extracted
    to fix, still present in the twin (#696). One mapper, so the next column
    cannot be added to one read and forgotten in another.
    """
    return Outcome(
        id=r["id"],
        request_id=r.get("request_id", ""),
        task_type=r.get("task_type", ""),
        model_used=r.get("model_used", ""),
        provider=r.get("provider", ""),
        success=bool(r["success"]),
        error_type=r.get("error_type", ""),
        response_time_ms=r.get("response_time_ms", 0),
        org_id=r.get("org_id", "") or "",
        team_id=r.get("team_id", ""),
        user_id=r.get("user_id", ""),
        agent_id=r.get("agent_id") or None,
        input_tokens=r.get("input_tokens", 0),
        output_tokens=r.get("output_tokens", 0),
        charged_microchips=r.get("charged_microchips", 0),
        pricing_version=r.get("pricing_version", ""),
        created_at=datetime.fromisoformat(r["created_at"]),
        project_id=r.get("project_id", "") or "",
        dag_id=r.get("dag_id", "") or "",
        dag_run_id=r.get("dag_run_id", "") or "",
        node_id=r.get("node_id", "") or "",
        thumb=r.get("thumb", "") or "",
        thumb_comment=r.get("thumb_comment", "") or "",
        eval_judge_score=r.get("eval_judge_score"),
    )
