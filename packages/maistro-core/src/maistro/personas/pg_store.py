"""PostgreSQL persistence for the canonical live Workspace Persona."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.runs.evidence_json import json_of, model_of

from .model import Persona
from .store import PersonaAlreadyExists, PersonaNotFound, WorkspacePersonaAlreadyExists

if TYPE_CHECKING:
    import asyncpg

#: The constraints migration 064 creates. Matched against
#: `UniqueViolationError.constraint_name` so a lost insert-after-check race is
#: translated into the domain error it means, while a violation on any other
#: constraint keeps its own identity.
PERSONA_PK_CONSTRAINT = "canonical_personas_pkey"
PERSONA_WORKSPACE_CONSTRAINT = "canonical_personas_workspace_id_key"


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
            try:
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
            except _unique_violation() as exc:
                # The SELECT checks above make sequential duplicates typed
                # errors; this branch is the insert-after-check race, where
                # another writer won between the check and the INSERT. Matched
                # on the constraint name (runs/pg_store.py records why), so a
                # violation on any other constraint keeps its own identity.
                constraint = str(getattr(exc, "constraint_name", "") or "")
                if constraint == PERSONA_WORKSPACE_CONSTRAINT:
                    raise WorkspacePersonaAlreadyExists(
                        f"workspace {persona.workspace_id!r} already owns a Persona"
                    ) from exc
                if constraint == PERSONA_PK_CONSTRAINT:
                    raise PersonaAlreadyExists(persona.id) from exc
                raise
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

    async def delete_for_workspace_in(self, conn: Any, workspace_id: str) -> None:
        """Delete on the connection whose transaction is already open.

        The Workspace delete calls this inside `TransactionalProjectScopeStore.
        transaction()`, so the Persona row commits — or rolls back — with the
        Workspace and its Project tree as one. Acquiring a second pooled
        connection here instead would serialize the two writes separately: a
        one-connection pool would deadlock, and a free one would let a later
        Workspace failure leave a deleted Persona beside a surviving Workspace.
        """
        await conn.execute("DELETE FROM canonical_personas WHERE workspace_id = $1", workspace_id)


def _unique_violation() -> type[Exception]:
    """The asyncpg uniqueness error, imported where the PostgreSQL path runs.

    The module imports ``asyncpg`` only for typing (same as the rest of the
    durable stores), so the exception class is resolved lazily: the SQLite and
    in-memory deployments never pay for it.
    """

    from asyncpg.exceptions import UniqueViolationError

    # asyncpg ships no type stubs, so the import is Any; the declared local is
    # the boundary where it becomes a type again.
    violation: type[Exception] = UniqueViolationError
    return violation


__all__ = ["PgPersonaStore"]
