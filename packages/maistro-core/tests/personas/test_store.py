from __future__ import annotations

import pytest

from maistro.personas.model import Persona
from maistro.personas.store import InMemoryPersonaStore, WorkspacePersonaAlreadyExists


def _persona(persona_id: str, workspace_id: str, *, name: str = "Default") -> Persona:
    return Persona(id=persona_id, workspace_id=workspace_id, name=name)


@pytest.mark.asyncio
async def test_workspace_resolves_its_single_persona() -> None:
    store = InMemoryPersonaStore()
    persona = await store.create(_persona("p-1", "ws-1"))

    assert await store.get("p-1") == persona
    assert await store.get_for_workspace("ws-1") == persona


@pytest.mark.asyncio
async def test_second_persona_for_same_workspace_is_rejected() -> None:
    store = InMemoryPersonaStore()
    await store.create(_persona("p-1", "ws-1"))

    with pytest.raises(WorkspacePersonaAlreadyExists):
        await store.create(_persona("p-2", "ws-1"))


@pytest.mark.asyncio
async def test_different_workspaces_each_have_one_persona() -> None:
    store = InMemoryPersonaStore()
    first = await store.create(_persona("p-1", "ws-1"))
    second = await store.create(_persona("p-2", "ws-2"))

    assert await store.get_for_workspace("ws-1") == first
    assert await store.get_for_workspace("ws-2") == second


@pytest.mark.asyncio
async def test_persona_update_preserves_workspace_cardinality() -> None:
    store = InMemoryPersonaStore()
    persona = await store.create(_persona("p-1", "ws-1"))
    saved = await store.update(persona.model_copy(update={"name": "Engineering"}))

    assert saved.name == "Engineering"
    assert await store.get_for_workspace("ws-1") == saved


@pytest.mark.asyncio
async def test_persona_cannot_move_into_an_occupied_workspace() -> None:
    store = InMemoryPersonaStore()
    first = await store.create(_persona("p-1", "ws-1"))
    await store.create(_persona("p-2", "ws-2"))

    with pytest.raises(WorkspacePersonaAlreadyExists):
        await store.update(first.model_copy(update={"workspace_id": "ws-2"}))


@pytest.mark.asyncio
async def test_deleting_persona_allows_replacement_for_workspace() -> None:
    store = InMemoryPersonaStore()
    await store.create(_persona("p-1", "ws-1"))
    await store.delete("p-1")

    replacement = await store.create(_persona("p-2", "ws-1", name="Replacement"))
    assert await store.get_for_workspace("ws-1") == replacement
