"""SQLite persistence for the canonical live Workspace Persona."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .model import Persona
from .store import (
    PersonaAlreadyExists,
    PersonaNotFound,
    WorkspacePersonaAlreadyExists,
)

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS canonical_personas (
    persona_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES canonical_workspaces(workspace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_canonical_personas_workspace
    ON canonical_personas(workspace_id);
"""


class SqlitePersonaStore:
    """Durable Persona store with one live Persona per Workspace."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    @asynccontextmanager
    async def _serialized_write(self) -> AsyncIterator[None]:
        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                await self._conn.rollback()
                raise
            else:
                await self._conn.commit()

    async def create(self, persona: Persona) -> Persona:
        async with self._serialized_write():
            if await self._exists(
                "SELECT 1 FROM canonical_personas WHERE persona_id = ?", (persona.id,)
            ):
                raise PersonaAlreadyExists(persona.id)
            if await self._exists(
                "SELECT 1 FROM canonical_personas WHERE workspace_id = ?", (persona.workspace_id,)
            ):
                raise WorkspacePersonaAlreadyExists(
                    f"workspace {persona.workspace_id!r} already owns a Persona"
                )
            await self._conn.execute(
                """INSERT INTO canonical_personas
                   (persona_id, workspace_id, name, created_at, updated_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    persona.id,
                    persona.workspace_id,
                    persona.name,
                    _iso(persona.created_at),
                    _iso(persona.updated_at),
                    persona.model_dump_json(),
                ),
            )
        return persona.model_copy(deep=True)

    async def get(self, persona_id: str) -> Persona | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_personas WHERE persona_id = ?", (persona_id,)
        )
        return Persona.model_validate_json(row[0]) if row is not None else None

    async def get_for_workspace(self, workspace_id: str) -> Persona | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_personas WHERE workspace_id = ?", (workspace_id,)
        )
        return Persona.model_validate_json(row[0]) if row is not None else None

    async def update(self, persona: Persona) -> Persona:
        async with self._serialized_write():
            current = await self.get(persona.id)
            if current is None:
                raise PersonaNotFound(persona.id)
            occupant = await self._fetchone(
                "SELECT persona_id FROM canonical_personas WHERE workspace_id = ?",
                (persona.workspace_id,),
            )
            if occupant is not None and occupant[0] != persona.id:
                raise WorkspacePersonaAlreadyExists(
                    f"workspace {persona.workspace_id!r} already owns a Persona"
                )
            updated = persona.model_copy(update={"updated_at": datetime.now(UTC)}, deep=True)
            await self._conn.execute(
                """UPDATE canonical_personas
                   SET workspace_id = ?, name = ?, updated_at = ?, payload = ?
                   WHERE persona_id = ?""",
                (
                    updated.workspace_id,
                    updated.name,
                    _iso(updated.updated_at),
                    updated.model_dump_json(),
                    updated.id,
                ),
            )
        return updated.model_copy(deep=True)

    async def delete(self, persona_id: str) -> None:
        async with self._serialized_write():
            cursor = await self._conn.execute(
                "DELETE FROM canonical_personas WHERE persona_id = ?", (persona_id,)
            )
            if cursor.rowcount == 0:
                raise PersonaNotFound(persona_id)

    async def delete_for_workspace(self, workspace_id: str) -> None:
        async with self._serialized_write():
            await self._conn.execute(
                "DELETE FROM canonical_personas WHERE workspace_id = ?", (workspace_id,)
            )

    async def _exists(self, sql: str, params: tuple[str, ...]) -> bool:
        return await self._fetchone(sql, params) is not None

    async def _fetchone(self, sql: str, params: tuple[str, ...]) -> tuple[Any, ...] | None:
        cursor = await self._conn.execute(sql, params)
        row = await cursor.fetchone()
        return tuple(row) if row is not None else None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


__all__ = ["SqlitePersonaStore"]
