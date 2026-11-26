from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.personas.model import Persona
from maistro.personas.store import (
    InMemoryPersonaStore,
    PersonaAlreadyExists,
    PersonaNotFound,
    WorkspacePersonaAlreadyExists,
)


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
async def test_a_naive_timestamp_is_read_as_utc_never_host_local() -> None:
    """Legacy naive Persona timestamps normalize to UTC (#1149's rule).

    A payload written before the model required awareness must not re-read as
    a different instant depending on the host's timezone: the validator pins
    naive values to UTC, so `03:00` written on a UTC-5 host reads as 03:00Z,
    not 08:00Z.
    """
    naive = datetime(2026, 1, 1, 3, 0, 0)
    persona = Persona(
        id="p-naive",
        workspace_id="ws-naive",
        name="Voice",
        created_at=naive,
        updated_at=naive,
    )

    assert persona.created_at.tzinfo is not None
    assert persona.created_at.utcoffset() == UTC.utcoffset(None)
    assert persona.created_at.hour == 3
    assert persona.updated_at == persona.created_at


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


@pytest.mark.asyncio
async def test_a_second_persona_with_a_used_id_is_rejected() -> None:
    """The id index, not just the Workspace index, is a uniqueness boundary."""
    store = InMemoryPersonaStore()
    await store.create(_persona("p-1", "ws-1"))

    with pytest.raises(PersonaAlreadyExists):
        await store.create(_persona("p-1", "ws-2"))


@pytest.mark.asyncio
async def test_updating_an_absent_persona_is_a_domain_error() -> None:
    store = InMemoryPersonaStore()

    with pytest.raises(PersonaNotFound):
        await store.update(_persona("p-absent", "ws-1"))


@pytest.mark.asyncio
async def test_a_reparent_update_frees_the_workspace_it_left() -> None:
    """Moving the Persona to another Workspace releases the old one.

    The occupancy index must follow the update, or the Workspace the Persona
    left stays permanently unownable — the compensation contract's other half.
    """
    store = InMemoryPersonaStore()
    await store.create(_persona("p-1", "ws-1"))

    moved = await store.update(_persona("p-1", "ws-2"))
    assert moved.workspace_id == "ws-2"

    successor = await store.create(_persona("p-2", "ws-1"))
    assert successor.workspace_id == "ws-1"


@pytest.mark.asyncio
async def test_deleting_an_absent_persona_is_a_domain_error() -> None:
    store = InMemoryPersonaStore()

    with pytest.raises(PersonaNotFound):
        await store.delete("p-absent")


@pytest.mark.asyncio
async def test_deleting_an_unknown_workspace_leaves_nothing_behind() -> None:
    """The Workspace-delete path is a purge, not a lookup: an absent
    Workspace is already in the wanted state."""
    store = InMemoryPersonaStore()
    await store.create(_persona("p-1", "ws-1"))

    await store.delete_for_workspace("ws-unknown")

    assert await store.get_for_workspace("ws-1") is not None


@pytest.mark.asyncio
async def test_the_transactional_delete_path_matches_the_plain_one() -> None:
    """`delete_for_workspace_in` is the wired Workspace delete's entry point.

    The reference store has no transaction to join, so it must behave exactly
    like `delete_for_workspace` — the durable twins prove the join itself.
    """
    store = InMemoryPersonaStore()
    await store.create(_persona("p-1", "ws-1"))

    await store.delete_for_workspace_in(conn=None, workspace_id="ws-1")

    assert await store.get("p-1") is None
    assert await store.get_for_workspace("ws-1") is None
