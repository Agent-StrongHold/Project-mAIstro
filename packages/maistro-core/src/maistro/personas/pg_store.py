"""PostgreSQL persistence for the canonical live Workspace Persona."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.runs.evidence_json import json_of, model_of

from .model import Persona
from .store import PersonaAlreadyExists, PersonaNotFound, WorkspacePersonaAlreadyExists

if TYPE_CHECKING:
    import asyncpg


class PgPersonaStore:
    """Durable Persona store with a database-enforced Workspace uniqueness key."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, persona: Persona) -> Persona:
        async with self._pool.acquire() as conn, conn.transaction():
            if await conn.fetchval(
                "SELECT 1 FROM canonical_personas WHERE persona_id = $1", persona.id
            ):
                raise PersonaAlreadyExists(persona.id)
            if await conn.fetchval(
                "SELECT 1 FROM canonical_personas WHERE workspace_id = $1", persona.workspace_id
            ):
                raise WorkspacePersonaAlreadyExists(
                    f"workspace {persona.workspace_id!r} already owns a Persona"
                )
            await conn.execute(
                """INSERT INTO canonical_personas
                   (persona_id, workspace_id, name, created_at, updated_at, payload)
                   VALUES ($1, $2, $3, $4, $5, $6::text::jsonb)""",
                persona.id,
                persona.workspace_id,
                persona.name,
                persona.created_at,
                persona.updated_at,
                json_of(persona),
            )
        return persona.model_copy(deep=True)

    async def get(self, persona_id: str) -> Persona | None:
        async with self._pool.acquire() as conn:
            payload = await conn.fetchval(
                "SELECT payload FROM canonical_personas WHERE persona_id = $1", persona_id
            )
        return model_of(Persona, payload) if payload is not None else None

    async def get_for_workspace(self, workspace_id: str) -> Persona | None:
        async with self._pool.acquire() as conn:
            payload = await conn.fetchval(
                "SELECT payload FROM canonical_personas WHERE workspace_id = $1", workspace_id
            )
        return model_of(Persona, payload) if payload is not None else None

    async def update(self, persona: Persona) -> Persona:
        updated = persona.model_copy(update={"updated_at": datetime.now(UTC)}, deep=True)
        async with self._pool.acquire() as conn, conn.transaction():
            current = await conn.fetchval(
                "SELECT payload FROM canonical_personas WHERE persona_id = $1 FOR UPDATE",
                persona.id,
            )
            if current is None:
                raise PersonaNotFound(persona.id)
            occupant = await conn.fetchval(
                """SELECT persona_id FROM canonical_personas
                   WHERE workspace_id = $1 AND persona_id <> $2""",
                persona.workspace_id,
                persona.id,
            )
            if occupant is not None:
                raise WorkspacePersonaAlreadyExists(
                    f"workspace {persona.workspace_id!r} already owns a Persona"
                )
            await conn.execute(
                """UPDATE canonical_personas
                   SET workspace_id = $1, name = $2, updated_at = $3, payload = $4::text::jsonb
                   WHERE persona_id = $5""",
                updated.workspace_id,
                updated.name,
                updated.updated_at,
                json_of(updated),
                updated.id,
            )
        return updated

    async def delete(self, persona_id: str) -> None:
        async with self._pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM canonical_personas WHERE persona_id = $1", persona_id
            )
        if status.endswith(" 0"):
            raise PersonaNotFound(persona_id)

    async def delete_for_workspace(self, workspace_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM canonical_personas WHERE workspace_id = $1", workspace_id
            )


__all__ = ["PgPersonaStore"]
