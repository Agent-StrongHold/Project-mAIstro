"""SQLite-backed prompt manager (homelab/single-instance deployments)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from maistro.persistence.pg_prompts import _parse_config

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    label TEXT,
    content TEXT NOT NULL,
    config TEXT
)
"""

_UNIQUE_LABEL_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompts_name_label
ON prompts (name, label) WHERE label IS NOT NULL
"""


class SqlitePromptManager:
    """SQLite-backed versioned prompt store implementing the same protocol as PgPromptManager."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        """Create the prompts table + unique (name, label) index if missing."""
        await self._conn.execute(_SCHEMA)
        await self._conn.execute(_UNIQUE_LABEL_INDEX)
        await self._conn.commit()

    async def get(self, name: str, *, label: str = "production") -> str:
        """Fetch prompt content by name and label."""
        content, _ = await self.get_with_config(name, label=label)
        return content

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = "production",
    ) -> tuple[str, dict[str, Any]]:
        """Fetch prompt text + config metadata."""
        cursor = await self._conn.execute(
            "SELECT content, config FROM prompts WHERE name = ? AND label = ?",
            (name, label),
        )
        row = await cursor.fetchone()
        if row:
            return str(row[0]), _parse_config(row[1])

        cursor = await self._conn.execute(
            "SELECT content, config FROM prompts WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        )
        row = await cursor.fetchone()
        if row:
            return str(row[0]), _parse_config(row[1])
        return "", {}

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
    ) -> None:
        """Create a new version of a prompt."""
        config_json = json.dumps(config or {})

        cursor = await self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM prompts WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
        next_ver: int = row[0] if row else 1

        if label:
            await self._conn.execute(
                "UPDATE prompts SET label = NULL WHERE name = ? AND label = ?",
                (name, label),
            )

        await self._conn.execute(
            "UPDATE prompts SET label = NULL WHERE name = ? AND label = 'latest'",
            (name,),
        )

        effective_label = label or "latest"
        await self._conn.execute(
            """INSERT INTO prompts (name, version, label, content, config)
               VALUES (?, ?, ?, ?, ?)""",
            (name, next_ver, effective_label, content, config_json),
        )

        if next_ver == 1 and effective_label != "production":
            await self._conn.execute(
                "DELETE FROM prompts WHERE name = ? AND label = 'production'",
                (name,),
            )
            await self._conn.execute(
                """INSERT INTO prompts (name, version, label, content, config)
                   VALUES (?, ?, 'production', ?, ?)""",
                (name, next_ver, content, config_json),
            )

        await self._conn.commit()
