"""Durable live Persona ownership across the SQLite restart boundary."""

from __future__ import annotations

import math

import aiosqlite
import pytest

from maistro.personas.model import Persona
from maistro.personas.sqlite_store import SqlitePersonaStore
from maistro.personas.store import (
    InMemoryPersonaStore,
    PersonaAlreadyExists,
    PersonaNotFound,
    WorkspacePersonaAlreadyExists,
)
from maistro.personas.wiring import wire_persona_store
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.types.errors import ConfigError
from maistro.workspaces.sqlite_store import SqliteWorkspaceStore
from maistro.workspaces.store import InMemoryWorkspaceStore


async def _stores(path):
    conn = await aiosqlite.connect(path)
    projects = SqliteProjectScopeStore(conn)
    await projects.ensure_schema()
    workspaces = SqliteWorkspaceStore(conn, project_store=projects)
    await workspaces.ensure_schema()
    personas = SqlitePersonaStore(conn)
    await personas.ensure_schema()
    return conn, workspaces, personas


@pytest.mark.asyncio
async def test_persona_survives_reopen_and_workspace_has_one_live_record(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    first_conn, workspaces, personas = await _stores(path)
    try:
        workspace = await workspaces.create(creator_user_id="alice", name="Design")
        saved = await personas.create(
            Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Design voice")
        )
        with pytest.raises(WorkspacePersonaAlreadyExists):
            await personas.create(
                Persona(id="persona-2", workspace_id=workspace.workspace_id, name="Other")
            )
    finally:
        await first_conn.close()

    second_conn, _, reopened = await _stores(path)
    try:
        assert await reopened.get("persona-1") == saved
        assert await reopened.get_for_workspace(workspace.workspace_id) == saved
    finally:
        await second_conn.close()


@pytest.mark.asyncio
async def test_in_memory_workspace_delete_purges_its_persona() -> None:
    personas = InMemoryPersonaStore()
    workspaces = InMemoryWorkspaceStore(persona_store=personas)
    workspace = await workspaces.create(creator_user_id="alice", name="Design")
    await personas.create(
        Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Voice")
    )

    await workspaces.delete(workspace.workspace_id)

    assert await personas.get_for_workspace(workspace.workspace_id) is None


class _FailingInMemoryPurge(InMemoryProjectScopeStore):
    async def purge_workspace(self, workspace_id: str) -> None:
        raise _PurgeBlewUp(workspace_id)


@pytest.mark.asyncio
async def test_a_failed_in_memory_delete_restores_the_workspace_and_its_persona() -> None:
    """The compensation is all-or-nothing across both ownership boundaries.

    The Workspace and memberships were already restored (#1121); the Persona
    deleted before the purge failed has to come back too, or the surviving
    Workspace restarts without the product context it owned.
    """
    personas = InMemoryPersonaStore()
    workspaces = InMemoryWorkspaceStore(
        project_store=_FailingInMemoryPurge(), persona_store=personas
    )
    workspace = await workspaces.create(creator_user_id="alice", name="Design")
    saved = await personas.create(
        Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Voice")
    )

    with pytest.raises(_PurgeBlewUp):
        await workspaces.delete(workspace.workspace_id)

    assert workspace.workspace_id in workspaces._workspaces
    assert await personas.get_for_workspace(workspace.workspace_id) == saved


@pytest.mark.asyncio
async def test_persona_update_keeps_snapshot_and_workspace_delete_cascades(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    conn, workspaces, personas = await _stores(path)
    try:
        workspace = await workspaces.create(creator_user_id="alice", name="Design")
        saved = await personas.create(
            Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Initial")
        )
        updated = await personas.update(saved.model_copy(update={"name": "Updated"}))
        assert updated.name == "Updated"
        assert saved.name == "Initial"

        await workspaces.delete(workspace.workspace_id)
        assert await personas.get(saved.id) is None
    finally:
        await conn.close()


async def test_wired_workspace_delete_takes_its_persona_in_the_same_transaction(tmp_path) -> None:
    """The regression the wiring alone can hide.

    With the Persona store attached the way `create_container` wires it, the
    Workspace delete already holds one transaction on the shared connection
    (#1121's shape). A Persona store that opens its own `BEGIN IMMEDIATE`
    there fails every wired deletion with "cannot start a transaction within
    a transaction"; the delete must ride the caller's transaction instead.
    """
    path = tmp_path / "canonical.db"
    conn = await aiosqlite.connect(path)
    try:
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        personas = SqlitePersonaStore(conn)
        await personas.ensure_schema()
        workspaces = SqliteWorkspaceStore(conn, project_store=projects, persona_store=personas)
        await workspaces.ensure_schema()

        workspace = await workspaces.create(creator_user_id="alice", name="Design")
        saved = await personas.create(
            Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Voice")
        )

        await workspaces.delete(workspace.workspace_id)

        assert await workspaces.get(workspace.workspace_id) is None
        assert await personas.get(saved.id) is None
        assert await personas.get_for_workspace(workspace.workspace_id) is None
    finally:
        await conn.close()


class _FailingPurgeProjects(SqliteProjectScopeStore):
    """The Project store, with its Workspace purge poisoned mid-transaction."""

    async def purge_workspace_in(self, conn, workspace_id) -> None:
        raise _PurgeBlewUp(workspace_id)


class _PurgeBlewUp(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_a_failed_workspace_delete_rolls_the_persona_back_with_it(tmp_path) -> None:
    """The Persona delete joins the Workspace delete's transaction, so a
    failure after it must leave the Persona in place — not pair a surviving
    Workspace with a deleted Persona (the durable shape of the compensation
    contract the in-memory store proves in test_store.py)."""
    path = tmp_path / "canonical.db"
    conn = await aiosqlite.connect(path)
    try:
        projects = _FailingPurgeProjects(conn)
        await projects.ensure_schema()
        personas = SqlitePersonaStore(conn)
        await personas.ensure_schema()
        workspaces = SqliteWorkspaceStore(conn, project_store=projects, persona_store=personas)
        await workspaces.ensure_schema()

        workspace = await workspaces.create(creator_user_id="alice", name="Design")
        saved = await personas.create(
            Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Voice")
        )

        with pytest.raises(_PurgeBlewUp):
            await workspaces.delete(workspace.workspace_id)

        assert await workspaces.get(workspace.workspace_id) is not None
        restored = await personas.get(saved.id)
        assert restored == saved
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_non_finite_persona_payload_survives_a_sqlite_round_trip(tmp_path) -> None:
    """The lossless evidence codec, not `model_dump_json()`.

    Pydantic's default JSON encoding turns NaN and Infinity into `null`, so a
    reopen read a different Persona than the one saved while the in-memory
    and PostgreSQL stores kept the value — three backends, three answers.
    The durable stores share one codec (`runs/evidence_json.py`) for the same
    reason the Run spine does (#132 review).
    """
    path = tmp_path / "canonical.db"
    conn, _, personas = await _stores(path)
    try:
        workspaces = SqliteWorkspaceStore(conn, project_store=SqliteProjectScopeStore(conn))
        await workspaces.ensure_schema()
        workspace = await workspaces.create(creator_user_id="alice", name="Design")

        saved = await personas.create(
            Persona(
                id="persona-1",
                workspace_id=workspace.workspace_id,
                name="Voice",
                taste={"dryness": float("nan"), "warmth": float("inf")},
            )
        )
        reloaded = await SqlitePersonaStore(conn).get(saved.id)

        assert reloaded is not None
        assert math.isnan(reloaded.taste["dryness"])
        assert math.isinf(reloaded.taste["warmth"])
        assert reloaded.taste["warmth"] > 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_a_second_sqlite_persona_with_a_used_id_is_rejected(tmp_path) -> None:
    """The id index, not just the Workspace index, is a uniqueness boundary."""
    path = tmp_path / "canonical.db"
    conn, _, personas = await _stores(path)
    try:
        workspaces = SqliteWorkspaceStore(conn, project_store=SqliteProjectScopeStore(conn))
        await workspaces.ensure_schema()
        first = await workspaces.create(creator_user_id="alice", name="Design")
        second = await workspaces.create(creator_user_id="bob", name="Research")
        await personas.create(
            Persona(id="persona-1", workspace_id=first.workspace_id, name="Voice")
        )

        with pytest.raises(PersonaAlreadyExists):
            await personas.create(
                Persona(id="persona-1", workspace_id=second.workspace_id, name="Other")
            )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_updating_an_absent_sqlite_persona_is_a_domain_error(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    conn, _, personas = await _stores(path)
    try:
        with pytest.raises(PersonaNotFound):
            await personas.update(Persona(id="persona-absent", workspace_id="ws-x", name="V"))
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_a_sqlite_reparent_into_an_occupied_workspace_is_rejected(tmp_path) -> None:
    """The one-Persona invariant holds on re-parent, not just on create."""
    path = tmp_path / "canonical.db"
    conn, _, personas = await _stores(path)
    try:
        workspaces = SqliteWorkspaceStore(conn, project_store=SqliteProjectScopeStore(conn))
        await workspaces.ensure_schema()
        first = await workspaces.create(creator_user_id="alice", name="Design")
        second = await workspaces.create(creator_user_id="bob", name="Research")
        await personas.create(
            Persona(id="persona-1", workspace_id=first.workspace_id, name="Voice")
        )
        squatter = await personas.create(
            Persona(id="persona-2", workspace_id=second.workspace_id, name="Other")
        )

        with pytest.raises(WorkspacePersonaAlreadyExists):
            await personas.update(
                Persona(id="persona-2", workspace_id=first.workspace_id, name="Other")
            )

        restored = await personas.get("persona-2")
        assert restored == squatter
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_deleting_an_absent_sqlite_persona_is_a_domain_error(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    conn, _, personas = await _stores(path)
    try:
        with pytest.raises(PersonaNotFound):
            await personas.delete("persona-absent")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_the_plain_sqlite_workspace_delete_removes_the_persona(tmp_path) -> None:
    """`delete_for_workspace` is the store's own API, wired callers aside.

    The wired Workspace delete rides `delete_for_workspace_in`; this is the
    same purge on the store's serialized writer, for callers that own the
    transaction themselves.
    """
    path = tmp_path / "canonical.db"
    conn, _, personas = await _stores(path)
    try:
        workspaces = SqliteWorkspaceStore(conn, project_store=SqliteProjectScopeStore(conn))
        await workspaces.ensure_schema()
        workspace = await workspaces.create(creator_user_id="alice", name="Design")
        saved = await personas.create(
            Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Voice")
        )

        await personas.delete_for_workspace(workspace.workspace_id)

        assert await personas.get(saved.id) is None
    finally:
        await conn.close()


# ----- the backend-selection wiring (#12) -----


class PgNamedInMemoryProjectScopeStore(InMemoryProjectScopeStore):
    """An in-memory store wearing a PostgreSQL name.

    `_backend_of` classifies by class name, so this routes `wire_persona_store`
    down the PostgreSQL branch without a server — exactly the mis-selection
    the ConfigErrors below guard.
    """


@pytest.mark.asyncio
async def test_the_wiring_selects_the_sqlite_store_and_creates_its_schema(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    conn = await aiosqlite.connect(path)
    try:
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()

        store = await wire_persona_store(conn, project_store=projects)

        assert isinstance(store, SqlitePersonaStore)
        # ensure_schema ran: the store is usable without a separate migration
        # step, which is the contract `create_container`'s SQLite wiring
        # relies on. The Persona row's foreign key needs a real Workspace.
        workspaces = SqliteWorkspaceStore(conn, project_store=projects)
        await workspaces.ensure_schema()
        workspace = await workspaces.create(creator_user_id="alice", name="Design")
        await store.create(
            Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Voice")
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_the_wiring_refuses_sqlite_without_a_connection() -> None:
    with pytest.raises(ConfigError, match="no connection reached the Persona store"):
        await wire_persona_store(None, project_store=SqliteProjectScopeStore(None))


@pytest.mark.asyncio
async def test_the_wiring_falls_back_to_memory_beside_the_reference_store() -> None:
    store = await wire_persona_store(None, project_store=InMemoryProjectScopeStore())

    assert isinstance(store, InMemoryPersonaStore)


@pytest.mark.asyncio
async def test_the_wiring_refuses_postgres_without_a_pool() -> None:
    with pytest.raises(ConfigError, match="no pool reached the Persona store"):
        await wire_persona_store(
            None, project_store=PgNamedInMemoryProjectScopeStore(), pg_pool=None
        )


@pytest.mark.asyncio
async def test_the_wiring_refuses_an_unmigrated_postgres_schema() -> None:
    class _UnmigratedPool:
        @staticmethod
        async def fetchval(_sql: str, _table: str):
            return None

    with pytest.raises(ConfigError, match="canonical Persona tables are missing"):
        await wire_persona_store(
            None, project_store=PgNamedInMemoryProjectScopeStore(), pg_pool=_UnmigratedPool()
        )
