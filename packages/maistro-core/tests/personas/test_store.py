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


@pytest.mark.asyncio
async def test_a_returned_persona_is_a_snapshot_not_a_live_view() -> None:
    """What `create` and `update` hand back must not track later edits.

    Every other test in this file compares a returned Persona against the
    store immediately, while the two are equal either way, so none of them
    can tell a snapshot from a live view. The difference shows only once the
    caller mutates its own object afterwards -- and a caller doing exactly
    that is the normal shape of editing a Persona's template catalog, where
    a leak would make the store's history a record of the present rather
    than of what was saved.

    Both of `update`'s copies are load-bearing here: the deep copy into
    storage and the deep copy on the way out. Making either one shallow
    alone leaves this passing; making both shallow is what aliases the
    caller's list into the returned snapshot.
    """
    store = InMemoryPersonaStore()
    created = await store.create(_persona("p-1", "ws-1"))

    working = created.model_copy(deep=True)
    working.node_template_ids.append("node-template-frank")
    added = await store.update(working)
    assert added.node_template_ids == ["node-template-frank"]

    working.node_template_ids.remove("node-template-frank")
    removed = await store.update(working)

    assert removed.node_template_ids == []
    assert added.node_template_ids == ["node-template-frank"]
    assert created.node_template_ids == []
