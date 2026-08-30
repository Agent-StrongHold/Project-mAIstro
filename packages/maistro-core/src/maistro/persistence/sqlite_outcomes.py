"""SQLite-backed outcome store (homelab/single-instance deployments)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from maistro.observability.correlation import observed_provenance
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
    run_id TEXT,
    node_run_id TEXT,
    attempt_id TEXT
)
"""

#: Nullable for the same reason migration 025 makes them nullable in
#: PostgreSQL: an outcome recorded with no execution in scope names none, and
#: `''` would name a Run whose id is empty (#709).
_PROVENANCE_COLUMNS = ("run_id", "node_run_id", "attempt_id")

_ALLOWED_GROUP_COLUMNS = frozenset({"user_id", "team_id", "model_used", "agent_id", "provider"})


class SqliteOutcomeStore:
    """SQLite-backed outcome store implementing the same protocol as PgOutcomeStore."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        """Create the outcomes table, and upgrade one created before its columns.

        The in-place branch is what makes this safe on a file that already holds
        outcomes: SQLite has no `ADD COLUMN IF NOT EXISTS`, and recreating the
        table would be the only alternative (#709).
        """
        await self._conn.execute(_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(outcomes)")
        columns = {row[1] for row in await cursor.fetchall()}
        for column in _PROVENANCE_COLUMNS:
            if column not in columns:
                await self._conn.execute(f"ALTER TABLE outcomes ADD COLUMN {column} TEXT")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outcomes_run_id ON outcomes (run_id)"
        )
        await self._conn.commit()

    async def record(self, outcome: Outcome) -> int:
        """Record an outcome, naming the execution that produced it (#709)."""
        provenance = observed_provenance(
            run_id=outcome.run_id,
            node_run_id=outcome.node_run_id,
            attempt_id=outcome.attempt_id,
        )
        cursor = await self._conn.execute(
            """INSERT INTO outcomes
               (request_id, task_type, model_used, provider,
                tool_calls, success, error_type, response_time_ms,
                team_id, user_id, agent_id,
                input_tokens, output_tokens, charged_microchips, pricing_version, created_at,
                run_id, node_run_id, attempt_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                provenance.run_id or None,
                provenance.node_run_id or None,
                provenance.attempt_id or None,
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

        outcomes = []
        for raw in rows:
            r = dict(zip(columns, raw, strict=True))
            outcomes.append(
                Outcome(
                    id=r["id"],
                    request_id=r.get("request_id", ""),
                    task_type=r.get("task_type", ""),
                    model_used=r.get("model_used", ""),
                    success=bool(r["success"]),
                    error_type=r.get("error_type", ""),
                    response_time_ms=r.get("response_time_ms", 0),
                    team_id=r.get("team_id", ""),
                    user_id=r.get("user_id", ""),
                    agent_id=r.get("agent_id") or None,
                    input_tokens=r.get("input_tokens", 0),
                    output_tokens=r.get("output_tokens", 0),
                    charged_microchips=r.get("charged_microchips", 0),
                    pricing_version=r.get("pricing_version", ""),
                    created_at=datetime.fromisoformat(r["created_at"]),
                )
            )
        return outcomes
