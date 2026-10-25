"""Persistence contract for the one live Persona owned by each Workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .model import Persona


class PersonaAlreadyExists(ValueError):
    """Raised when a Persona identity already exists."""


class WorkspacePersonaAlreadyExists(ValueError):
    """Raised when a Workspace already owns its live Persona."""


class PersonaNotFound(KeyError):
    """Raised when a Persona identity is not present."""


@runtime_checkable
class PersonaStore(Protocol):
    """Store contract enforcing at most one live Persona per Workspace.

    A Workspace may transiently have zero Personas during onboarding/migration,
    but canonical product flows converge to one Persona and this store never
    permits two live Personas for the same Workspace.
    """

    async def create(self, persona: Persona) -> Persona: ...

    async def get(self, persona_id: str) -> Persona | None: ...

    async def get_for_workspace(self, workspace_id: str) -> Persona | None: ...

    async def update(self, persona: Persona) -> Persona: ...

    async def delete(self, persona_id: str) -> None: ...


class InMemoryPersonaStore:
    """Reference Persona store with a uniqueness index on ``workspace_id``."""

    def __init__(self) -> None:
        self._by_id: dict[str, Persona] = {}
        self._persona_id_by_workspace: dict[str, str] = {}

    async def create(self, persona: Persona) -> Persona:
        if persona.id in self._by_id:
            raise PersonaAlreadyExists(persona.id)
        existing = self._persona_id_by_workspace.get(persona.workspace_id)
        if existing is not None:
            raise WorkspacePersonaAlreadyExists(
                f"workspace {persona.workspace_id!r} already owns persona {existing!r}"
            )
        stored = persona.model_copy(deep=True)
        self._by_id[stored.id] = stored
        self._persona_id_by_workspace[stored.workspace_id] = stored.id
        return stored.model_copy(deep=True)

    async def get(self, persona_id: str) -> Persona | None:
        persona = self._by_id.get(persona_id)
        return persona.model_copy(deep=True) if persona is not None else None

    async def get_for_workspace(self, workspace_id: str) -> Persona | None:
        persona_id = self._persona_id_by_workspace.get(workspace_id)
        return await self.get(persona_id) if persona_id is not None else None

    async def update(self, persona: Persona) -> Persona:
        current = self._by_id.get(persona.id)
        if current is None:
            raise PersonaNotFound(persona.id)

        occupant = self._persona_id_by_workspace.get(persona.workspace_id)
        if occupant is not None and occupant != persona.id:
            raise WorkspacePersonaAlreadyExists(
                f"workspace {persona.workspace_id!r} already owns persona {occupant!r}"
            )

        if current.workspace_id != persona.workspace_id:
            self._persona_id_by_workspace.pop(current.workspace_id, None)

        updated = persona.model_copy(update={"updated_at": datetime.now(UTC)}, deep=True)
        self._by_id[updated.id] = updated
        self._persona_id_by_workspace[updated.workspace_id] = updated.id
        return updated.model_copy(deep=True)

    async def delete(self, persona_id: str) -> None:
        persona = self._by_id.pop(persona_id, None)
        if persona is None:
            raise PersonaNotFound(persona_id)
        self._persona_id_by_workspace.pop(persona.workspace_id, None)


__all__ = [
    "InMemoryPersonaStore",
    "PersonaAlreadyExists",
    "PersonaNotFound",
    "PersonaStore",
    "WorkspacePersonaAlreadyExists",
]
