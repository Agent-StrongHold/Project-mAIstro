"""SQLite-backed prompt manager (homelab/single-instance deployments).

The same two tables as the PostgreSQL twin, with the same two keys, so the two
backends store the same shape rather than each agreeing with itself
(ADR-083026-427c). Where PostgreSQL serializes same-name writers with a
per-name advisory lock, SQLite serializes every writer with `BEGIN IMMEDIATE`:
its write lock is the whole database, which is the right granularity for the
single instance this store serves.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from maistro.persistence.pg_prompts import (
    _DEFAULT_LABEL,
    _PRODUCTION_LABEL,
    _parse_config,
)

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    config TEXT,
    PRIMARY KEY (name, version)
);

CREATE TABLE IF NOT EXISTS prompt_labels (
    name TEXT NOT NULL,
    label TEXT NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (name, label),
    FOREIGN KEY (name, version) REFERENCES prompts (name, version) ON DELETE CASCADE
);
"""


class SqlitePromptManager:
    """SQLite-backed versioned prompt store implementing the same protocol as PgPromptManager."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        # One aiosqlite connection is shared by every caller, so two concurrent
        # writers would issue two `BEGIN IMMEDIATE`s on it and the second would
        # raise "cannot start a transaction within a transaction" -- a spurious
        # error where the caller should have waited. The same lock the
        # Workspace and Run stores carry, for the same reason.
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create the prompt tables if missing, and mean the foreign key.

        SQLite parses `REFERENCES` and then ignores it unless
        `PRAGMA foreign_keys` is on -- off by default, per connection, forever,
        for backwards compatibility. A declared-but-unenforced constraint is
        worse than none: it reads in the schema as a guarantee the database is
        not making, which is the shape of the whole defect this store is being
        fixed for.
        """
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def get(self, name: str, *, label: str = _PRODUCTION_LABEL) -> str:
        """Fetch prompt content by name and label."""
        content, _ = await self.get_with_config(name, label=label)
        return content

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = _PRODUCTION_LABEL,
    ) -> tuple[str, dict[str, Any]]:
        """Fetch prompt text + config metadata, falling back to the highest version."""
        cursor = await self._conn.execute(
            """SELECT p.content, p.config
               FROM prompt_labels l
               JOIN prompts p ON p.name = l.name AND p.version = l.version
               WHERE l.name = ? AND l.label = ?""",
            (name, label),
        )
        row = await cursor.fetchone()
        if row is None:
            cursor = await self._conn.execute(
                "SELECT content, config FROM prompts WHERE name = ? ORDER BY version DESC LIMIT 1",
                (name,),
            )
            row = await cursor.fetchone()
        if row is not None:
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
        """Create a version of a prompt and point its labels at it, atomically."""
        config_json = json.dumps(config or {})
        effective_label = label or _DEFAULT_LABEL

        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                version = await self._version_for(name, content, config_json)

                for moving in {_DEFAULT_LABEL, effective_label}:
                    await self._conn.execute(
                        """INSERT INTO prompt_labels (name, label, version)
                           VALUES (?, ?, ?)
                           ON CONFLICT (name, label) DO UPDATE SET version = excluded.version""",
                        (name, moving, version),
                    )

                await self._conn.execute(
                    """INSERT INTO prompt_labels (name, label, version)
                       VALUES (?, ?, ?)
                       ON CONFLICT (name, label) DO NOTHING""",
                    (name, _PRODUCTION_LABEL, version),
                )
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

    async def _version_for(self, name: str, content: str, config_json: str) -> int:
        """The version this write belongs to: the head on an exact retry, else a new one."""
        cursor = await self._conn.execute(
            "SELECT version, content, config FROM prompts "
            "WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        )
        head = await cursor.fetchone()
        if (
            head is not None
            and str(head[1]) == content
            and _parse_config(head[2]) == json.loads(config_json)
        ):
            return int(head[0])

        version = int(head[0]) + 1 if head is not None else 1
        await self._conn.execute(
            "INSERT INTO prompts (name, version, content, config) VALUES (?, ?, ?, ?)",
            (name, version, content, config_json),
        )
        return version
